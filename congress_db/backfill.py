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
from .ingest_utterances import KNOWN_HTML_UNAVAILABLE_MNTS_IDS, ingest_utterances
from .ingest_votes import ingest_votes
from .progress import safe_print
from .sanity_check import run_sanity_check
from .session_groups import ingest_session_groups
from .validate_session_groups import validate_session_groups

OFFICIAL_API_BENCHMARK_SAMPLE_SIZE = 1000
OFFICIAL_SCRAPE_BENCHMARK_SAMPLE_SIZE = 300


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
    return run_staged_ingest(
        mode="backfill",
        stages=stages or build_default_backfill_stages(),
        run_metadata=run_metadata,
    )


def run_incremental_stages(
    *,
    stages: Sequence[BackfillStage],
    run_metadata: Mapping[str, Any] | None = None,
) -> BackfillRunResult:
    """증분 동기화 stage 묶음을 실행하고 ingest run 상태를 남긴다."""
    return run_staged_ingest(
        mode="incremental",
        stages=stages,
        run_metadata=run_metadata,
    )


def run_staged_ingest(
    *,
    mode: str,
    stages: Sequence[BackfillStage],
    run_metadata: Mapping[str, Any] | None = None,
) -> BackfillRunResult:
    """지정한 mode로 stage 묶음을 실행하고 ingest run 상태를 남긴다."""
    selected_stages = tuple(stages or build_default_backfill_stages())
    metadata = dict(run_metadata or {})
    run_id = _start_ingest_run(mode, metadata)
    stage_summaries: dict[str, Mapping[str, Any]] = {}
    dead_letter_count = 0

    try:
        for stage in selected_stages:
            safe_print(f"[backfill] stage={stage.name} start", flush=True)
            stage_result = stage.run()
            stage_summaries[stage.name] = _jsonable(stage_result.summary)
            dead_letter_count += _record_dead_letters(run_id, stage_result.dead_letters)
            _persist_summary(run_id, metadata, stage_summaries, dead_letter_count)
            safe_print(f"[backfill] stage={stage.name} done", flush=True)
    except BaseException as exc:
        error_detail = str(exc) or exc.__class__.__name__
        error = f"{stage.name}: {error_detail}"
        _finish_ingest_run(
            run_id,
            status="failed",
            metadata=metadata,
            stage_summaries=stage_summaries,
            dead_letter_count=dead_letter_count,
            error=error,
        )
        raise

    status = "degraded_success" if dead_letter_count else "success"
    _finish_ingest_run(
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
    load_utterance_ids = load_meeting_ids_fn or load_utterance_target_meeting_ids
    session_group_target_ids: tuple[int, ...] = ()

    def run_members() -> StageResult:
        return _stage_from_result(ingest_members_fn())

    def run_bills() -> StageResult:
        result = ingest_bills_fn(
            limit_pct=1.0,
            benchmark_sample_size=OFFICIAL_API_BENCHMARK_SAMPLE_SIZE,
        )
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
        result = ingest_votes_fn(
            limit_pct=1.0,
            benchmark_sample_size=OFFICIAL_API_BENCHMARK_SAMPLE_SIZE,
            allow_partial=True,
        )
        failures = getattr(result, "vote_row_failures", ())
        dead_letters = tuple(
            DeadLetterDraft(
                source="votes.rows",
                stage="fetch",
                item_key=str(failure.bill_id),
                payload={"bill_id": failure.bill_id},
                error=failure.error,
            )
            for failure in failures
        )
        return _stage_from_result(result, exclude=("vote_row_failures",), dead_letters=dead_letters)

    def run_meetings() -> StageResult:
        return _stage_from_result(
            ingest_meetings_fn(
                calibration_limit=None,
                benchmark_sample_size=OFFICIAL_API_BENCHMARK_SAMPLE_SIZE,
            )
        )

    def run_utterances() -> StageResult:
        nonlocal session_group_target_ids
        meeting_ids = tuple(load_utterance_ids())
        if not meeting_ids:
            session_group_target_ids = tuple(load_ids())
            return StageResult(
                summary={
                    "meeting_count": 0,
                    "scraped_meeting_count": 0,
                    "scraped_meeting_ids": (),
                    "utterance_count": 0,
                    "selected_worker_count": None,
                    "retry_count": 0,
                    "retried_meeting_count": 0,
                    "scrape_error_count": 0,
                    "member_mapped_count": 0,
                    "sample_errors": (),
                    "skipped_reason": "no missing or explicitly targeted meetings",
                }
            )
        result = ingest_utterances_fn(
            calibration_limit=max(len(meeting_ids), 1),
            meeting_ids=meeting_ids,
            benchmark_sample_size=OFFICIAL_SCRAPE_BENCHMARK_SAMPLE_SIZE,
            allow_partial=True,
        )
        session_group_target_ids = tuple(
            getattr(result, "scraped_meeting_ids", meeting_ids),
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
        target_ids = tuple(load_ids()) if load_meeting_ids_fn else session_group_target_ids
        if not target_ids:
            return StageResult(
                summary={
                    "meeting_count": 0,
                    "skipped_meeting_count": 0,
                    "group_count": 0,
                    "utterance_link_count": 0,
                    "skipped_reason": "no utterance changes to regroup",
                }
            )
        return _stage_from_result(ingest_session_groups_fn(meeting_ids=target_ids))

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
    excluded_ids = sorted(KNOWN_HTML_UNAVAILABLE_MNTS_IDS)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id
            FROM meetings
            WHERE NOT (mnts_id = ANY(%s))
            ORDER BY conf_date DESC, mnts_id DESC
            """,
            (excluded_ids,),
        )
        return tuple(row[0] for row in cur.fetchall())


def load_utterance_target_meeting_ids() -> tuple[int, ...]:
    """HTML 발언이 비어 있어 실제 스크래핑이 필요한 meeting id만 반환한다."""
    excluded_ids = sorted(KNOWN_HTML_UNAVAILABLE_MNTS_IDS)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.mnts_id
            FROM meetings m
            LEFT JOIN utterances u ON u.meeting_id = m.mnts_id
            WHERE NOT (m.mnts_id = ANY(%s))
            GROUP BY m.mnts_id, m.conf_date
            HAVING COUNT(u.id) = 0
            ORDER BY m.conf_date DESC, m.mnts_id DESC
            """,
            (excluded_ids,),
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


def _start_ingest_run(mode: str, metadata: Mapping[str, Any]) -> int:
    with get_conn() as conn:
        run_id = start_run(
            conn,
            mode=mode,
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


def _finish_ingest_run(
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
