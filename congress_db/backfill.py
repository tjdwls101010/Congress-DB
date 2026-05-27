"""초기 전체 백필 orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .data_completeness import generate_data_completeness_report
from .db import get_conn
from .ingest_bills import ingest_bills
from .ingest_meetings import ingest_meetings
from .ingest_members import ingest_members
from .ingest_state import (
    finish_run,
    record_dead_letter,
    start_run,
    update_run_summary,
)
from .ingest_utterances import ingest_utterances
from .ingest_votes import ingest_votes
from .sanity_check import run_sanity_check
from .session_groups import ingest_session_groups
from .validate_session_groups import validate_session_groups


@dataclass(frozen=True)
class DeadLetterDraft:
    """backfill stage가 남긴 item-level 최종 실패."""

    source: str
    stage: str
    item_key: str
    error: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class StageResult:
    """한 backfill stage의 관찰 가능한 결과."""

    summary: Mapping[str, Any]
    dead_letters: tuple[DeadLetterDraft, ...] = ()


@dataclass(frozen=True)
class BackfillStage:
    """backfill runner가 순서대로 실행할 stage."""

    name: str
    run: Callable[[], StageResult]


@dataclass(frozen=True)
class BackfillRunResult:
    """backfill run 최종 결과."""

    run_id: int
    status: str
    stage_summaries: Mapping[str, Mapping[str, Any]]
    dead_letter_count: int


def run_backfill(
    *,
    stages: Sequence[BackfillStage] | None = None,
    run_metadata: Mapping[str, Any] | None = None,
) -> BackfillRunResult:
    """로컬 100% 백필을 실행하고 ingest run 상태를 남긴다."""
    selected_stages = tuple(stages or build_default_backfill_stages())
    metadata = dict(run_metadata or {})
    run_id = _start_backfill_run(metadata)
    stage_summaries: dict[str, Mapping[str, Any]] = {}
    dead_letter_count = 0

    try:
        for stage in selected_stages:
            print(f"[backfill] stage={stage.name} start", flush=True)
            stage_result = stage.run()
            stage_summaries[stage.name] = _jsonable(stage_result.summary)
            dead_letter_count += _record_dead_letters(run_id, stage_result.dead_letters)
            _persist_summary(run_id, metadata, stage_summaries, dead_letter_count)
            print(f"[backfill] stage={stage.name} done", flush=True)
    except Exception as exc:
        error = f"{stage.name}: {exc}"
        _finish_backfill_run(
            run_id,
            status="failed",
            metadata=metadata,
            stage_summaries=stage_summaries,
            dead_letter_count=dead_letter_count,
            error=error,
        )
        raise

    status = "degraded_success" if dead_letter_count else "success"
    _finish_backfill_run(
        run_id,
        status=status,
        metadata=metadata,
        stage_summaries=stage_summaries,
        dead_letter_count=dead_letter_count,
    )
    return BackfillRunResult(
        run_id=run_id,
        status=status,
        stage_summaries=stage_summaries,
        dead_letter_count=dead_letter_count,
    )


def build_default_backfill_stages(
    *,
    ingest_members_fn: Callable[..., object] = ingest_members,
    ingest_bills_fn: Callable[..., object] = ingest_bills,
    ingest_votes_fn: Callable[..., object] = ingest_votes,
    ingest_meetings_fn: Callable[..., object] = ingest_meetings,
    ingest_utterances_fn: Callable[..., object] = ingest_utterances,
    ingest_session_groups_fn: Callable[..., object] = ingest_session_groups,
    validate_session_groups_fn: Callable[..., object] = validate_session_groups,
    run_sanity_check_fn: Callable[..., object] = run_sanity_check,
    generate_data_completeness_report_fn: Callable[..., object] = generate_data_completeness_report,
    load_meeting_ids_fn: Callable[[], Sequence[int]] | None = None,
) -> tuple[BackfillStage, ...]:
    """기존 ingest Module을 full-load 파라미터로 묶은 기본 stage 목록."""
    load_ids = load_meeting_ids_fn or load_all_meeting_ids

    def run_members() -> StageResult:
        return _stage_from_result(ingest_members_fn())

    def run_bills() -> StageResult:
        result = ingest_bills_fn(limit_pct=1.0)
        failures = getattr(result, "summary_failures", ())
        dead_letters = tuple(
            DeadLetterDraft(
                source="bills.summary",
                stage="fetch",
                item_key=str(failure.bill_no),
                payload={"bill_no": failure.bill_no},
                error=failure.error,
            )
            for failure in failures
        )
        return _stage_from_result(result, exclude=("summary_failures",), dead_letters=dead_letters)

    def run_votes() -> StageResult:
        return _stage_from_result(ingest_votes_fn(limit_pct=1.0))

    def run_meetings() -> StageResult:
        return _stage_from_result(ingest_meetings_fn(calibration_limit=None))

    def run_utterances() -> StageResult:
        meeting_ids = tuple(load_ids())
        result = ingest_utterances_fn(
            calibration_limit=max(len(meeting_ids), 1),
            meeting_ids=meeting_ids,
            allow_partial=True,
        )
        failures = getattr(result, "scrape_failures", ())
        dead_letters = tuple(
            DeadLetterDraft(
                source="minutes.html",
                stage="fetch",
                item_key=str(failure.mnts_id),
                payload={"mnts_id": failure.mnts_id},
                error=failure.error,
            )
            for failure in failures
        )
        return _stage_from_result(result, exclude=("scrape_failures",), dead_letters=dead_letters)

    def run_session_groups() -> StageResult:
        return _stage_from_result(ingest_session_groups_fn(meeting_ids=tuple(load_ids())))

    def run_validation() -> StageResult:
        result = validate_session_groups_fn()
        return _stage_from_result(result)

    def run_sanity() -> StageResult:
        result = run_sanity_check_fn()
        return _stage_from_result(result)

    def run_data_completeness() -> StageResult:
        result = generate_data_completeness_report_fn()
        return _stage_from_result(result)

    return (
        BackfillStage("members", run_members),
        BackfillStage("bills", run_bills),
        BackfillStage("votes", run_votes),
        BackfillStage("meetings", run_meetings),
        BackfillStage("utterances", run_utterances),
        BackfillStage("session_groups", run_session_groups),
        BackfillStage("validate_session_groups", run_validation),
        BackfillStage("sanity_check", run_sanity),
        BackfillStage("data_completeness", run_data_completeness),
    )


def load_all_meeting_ids() -> tuple[int, ...]:
    """현재 DB에 적재된 모든 meeting id를 안정적인 순서로 반환한다."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id
            FROM meetings
            ORDER BY conf_date DESC, mnts_id DESC
            """
        )
        return tuple(row[0] for row in cur.fetchall())


def _stage_from_result(
    result: object,
    *,
    exclude: Sequence[str] = (),
    dead_letters: tuple[DeadLetterDraft, ...] = (),
) -> StageResult:
    summary = _summary_from_result(result, exclude=exclude)
    return StageResult(summary=summary, dead_letters=dead_letters)


def _summary_from_result(result: object, *, exclude: Sequence[str] = ()) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        raw: dict[str, Any] = dict(result)
    elif is_dataclass(result) and not isinstance(result, type):
        raw = asdict(result)
    elif hasattr(result, "__dict__"):
        raw = dict(vars(result))
    else:
        raw = {"result": str(result)}
    for key in exclude:
        raw.pop(key, None)
    return _jsonable(raw)


def _start_backfill_run(metadata: Mapping[str, Any]) -> int:
    with get_conn() as conn:
        run_id = start_run(
            conn,
            mode="backfill",
            summary=_run_summary(metadata, {}, 0),
        )
        conn.commit()
    return run_id


def _record_dead_letters(
    run_id: int,
    dead_letters: Sequence[DeadLetterDraft],
) -> int:
    if not dead_letters:
        return 0
    with get_conn() as conn:
        for dead_letter in dead_letters:
            record_dead_letter(
                conn,
                run_id=run_id,
                source=dead_letter.source,
                stage=dead_letter.stage,
                item_key=dead_letter.item_key,
                payload=dead_letter.payload,
                error=dead_letter.error,
            )
        conn.commit()
    return len(dead_letters)


def _persist_summary(
    run_id: int,
    metadata: Mapping[str, Any],
    stage_summaries: Mapping[str, Mapping[str, Any]],
    dead_letter_count: int,
) -> None:
    with get_conn() as conn:
        update_run_summary(
            conn,
            run_id,
            _run_summary(metadata, stage_summaries, dead_letter_count),
        )
        conn.commit()


def _finish_backfill_run(
    run_id: int,
    *,
    status: str,
    metadata: Mapping[str, Any],
    stage_summaries: Mapping[str, Mapping[str, Any]],
    dead_letter_count: int,
    error: str | None = None,
) -> None:
    with get_conn() as conn:
        finish_run(
            conn,
            run_id,
            status=status,
            summary=_run_summary(metadata, stage_summaries, dead_letter_count),
            error=error,
        )
        conn.commit()


def _run_summary(
    metadata: Mapping[str, Any],
    stage_summaries: Mapping[str, Mapping[str, Any]],
    dead_letter_count: int,
) -> dict[str, Any]:
    summary = dict(metadata)
    summary.update(
        {
            "stages": _jsonable(stage_summaries),
            "dead_letter_count": dead_letter_count,
        }
    )
    return summary


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    return value
