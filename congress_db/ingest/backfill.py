"""초기 전체 백필 orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..core.db import get_conn
from ..core.progress import safe_print
from ..ops.data_completeness import generate_data_completeness_report
from ..ops.sanity_check import run_sanity_check
from .ingest_bills import ingest_bills
from .ingest_members import ingest_members
from .ingest_state import (
    finish_run,
    record_dead_letter,
    start_run,
    update_run_summary,
)
from .ingest_votes import ingest_votes

OFFICIAL_API_BENCHMARK_SAMPLE_SIZE = 1000


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
    run_sanity_check_fn: Callable[..., object] = run_sanity_check,
    generate_data_completeness_report_fn: Callable[..., object] = generate_data_completeness_report,
) -> tuple[BackfillStage, ...]:
    """기존 ingest Module을 full-load 파라미터로 묶은 기본 stage 목록."""

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
        BackfillStage("sanity_check", run_sanity),
        BackfillStage("data_completeness", run_data_completeness),
    )


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
