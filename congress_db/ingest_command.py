"""공식 단일 수집 명령 Interface."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from .backfill import (
    BackfillRunResult,
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    build_default_backfill_stages,
    load_utterance_target_meeting_ids,
    run_backfill,
    run_incremental_stages,
)
from .data_completeness import generate_data_completeness_report
from .dead_letter_retry import retry_dead_letters
from .db import get_conn
from .ingest_bills import ingest_bills
from .ingest_meetings import ingest_meetings
from .ingest_members import ingest_members
from .ingest_state import upsert_cursor
from .ingest_utterances import ingest_utterances
from .ingest_votes import ingest_votes
from .migration_readiness import generate_migration_readiness_report
from .sanity_check import run_sanity_check
from .session_groups import ingest_session_groups
from .validate_session_groups import validate_session_groups

ModeRequest = Literal["auto", "backfill", "incremental"]
RunMode = Literal["backfill", "incremental"]

REQUIRED_CURSOR_SPECS: tuple[tuple[str, str, int], ...] = (
    ("members", "full_refresh", 0),
    ("bills", "propose_or_proc_dt", 30),
    ("votes", "vote_date", 30),
    ("meetings", "conf_date", 30),
    ("utterances", "meeting_id_set", 30),
    ("session_groups", "meeting_id_set", 30),
)


@dataclass(frozen=True)
class IngestCommandResult:
    """공식 수집 명령 실행 결과."""

    mode: RunMode
    run_id: int
    status: str
    stage_summaries: Mapping[str, Mapping[str, Any]]
    dead_letter_count: int


def run_ingest(
    *,
    mode: ModeRequest = "auto",
    force_meeting_ids: Sequence[int] = (),
    now_fn: Callable[[], datetime] | None = None,
) -> IngestCommandResult:
    """PM/운영자가 쓰는 단일 수집 명령을 실행한다."""
    now = (now_fn or (lambda: datetime.now(UTC)))()
    selected_mode = select_ingest_mode(mode)
    print(f"[ingest] mode={selected_mode}", flush=True)

    if selected_mode == "backfill":
        stages = build_official_backfill_stages()
        result = run_backfill(
            stages=stages,
            run_metadata={
                "entrypoint": "ingest",
                "requested_mode": mode,
                "selected_mode": selected_mode,
            },
        )
    else:
        stages = build_incremental_stages(force_meeting_ids=force_meeting_ids)
        result = run_incremental_stages(
            stages=stages,
            run_metadata={
                "entrypoint": "ingest",
                "requested_mode": mode,
                "selected_mode": selected_mode,
                "force_meeting_ids": sorted(set(force_meeting_ids)),
            },
        )

    if result.status == "success":
        advance_required_cursors(result.run_id, now)

    return IngestCommandResult(
        mode=selected_mode,
        run_id=result.run_id,
        status=result.status,
        stage_summaries=result.stage_summaries,
        dead_letter_count=result.dead_letter_count,
    )


def select_ingest_mode(mode: ModeRequest = "auto") -> RunMode:
    """DB 상태와 요청값으로 backfill/incremental 실행 mode를 고른다."""
    if mode != "auto":
        return decide_ingest_mode(
            mode,
            successful_backfill=False,
            required_cursors=False,
        )
    if not has_successful_backfill():
        return "backfill"
    if not has_required_cursors():
        seed_cursors_from_latest_backfill()
    return decide_ingest_mode(
        mode,
        successful_backfill=True,
        required_cursors=has_required_cursors(),
    )


def decide_ingest_mode(
    mode: str,
    *,
    successful_backfill: bool,
    required_cursors: bool,
) -> RunMode:
    """순수 mode 결정 규칙."""
    if mode in ("backfill", "incremental"):
        return mode  # type: ignore[return-value]
    if mode != "auto":
        raise ValueError("mode must be one of: auto, backfill, incremental")
    if not successful_backfill:
        return "backfill"
    return "incremental" if required_cursors else "backfill"


def has_successful_backfill() -> bool:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM ingest_runs
                WHERE mode = 'backfill' AND status = 'success'
            )
            """
        )
        return bool(cur.fetchone()[0])


def has_required_cursors() -> bool:
    required_sources = [source for source, _, _ in REQUIRED_CURSOR_SPECS]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source
            FROM ingest_cursors
            WHERE source = ANY(%s)
            """,
            (required_sources,),
        )
        found = {row[0] for row in cur.fetchall()}
    return set(required_sources).issubset(found)


def seed_cursors_from_latest_backfill() -> bool:
    """기존 성공 백필이 있는데 cursor만 없을 때 기준점을 만든다."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, finished_at
            FROM ingest_runs
            WHERE mode = 'backfill' AND status = 'success'
            ORDER BY finished_at DESC NULLS LAST, started_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            return False
        run_id, finished_at = row
        cursor_value = finished_at or datetime.now(UTC)
        for source, cursor_kind, overlap_days in REQUIRED_CURSOR_SPECS:
            upsert_cursor(
                conn,
                source=source,
                cursor_kind=cursor_kind,
                cursor_value=cursor_value,
                updated_run_id=run_id,
                overlap_days=overlap_days,
            )
        conn.commit()
    return True


def advance_required_cursors(run_id: int, cursor_value: datetime) -> None:
    """성공한 공식 수집 run 뒤 source cursor를 전진시킨다."""
    with get_conn() as conn:
        for source, cursor_kind, overlap_days in REQUIRED_CURSOR_SPECS:
            upsert_cursor(
                conn,
                source=source,
                cursor_kind=cursor_kind,
                cursor_value=cursor_value,
                updated_run_id=run_id,
                overlap_days=overlap_days,
            )
        conn.commit()


def build_official_backfill_stages() -> tuple[BackfillStage, ...]:
    """공식 백필 stage: dead letter 재시도와 readiness까지 포함한다."""
    return (
        BackfillStage("retry_dead_letters", _run_dead_letter_retry),
        *build_default_backfill_stages(),
        BackfillStage("migration_readiness", _run_migration_readiness),
    )


def build_incremental_stages(
    *,
    force_meeting_ids: Sequence[int] = (),
) -> tuple[BackfillStage, ...]:
    """공식 증분 stage 묶음."""
    forced_ids = tuple(sorted(set(force_meeting_ids)))
    touched_meeting_ids: tuple[int, ...] = ()
    regroup_meeting_ids: tuple[int, ...] = ()

    def run_members() -> StageResult:
        return _stage_from_result(ingest_members())

    def run_bills() -> StageResult:
        return _stage_from_result(ingest_bills(limit_pct=1.0))

    def run_votes() -> StageResult:
        return _stage_from_result(ingest_votes(limit_pct=1.0))

    def run_meetings() -> StageResult:
        nonlocal touched_meeting_ids
        result = ingest_meetings(calibration_limit=None)
        touched_meeting_ids = tuple(
            sorted(set(result.new_meeting_ids) | set(result.changed_meeting_ids) | set(forced_ids))
        )
        return _stage_from_result(result)

    def run_utterances() -> StageResult:
        nonlocal regroup_meeting_ids
        missing_ids = set(load_utterance_target_meeting_ids())
        target_ids = tuple(sorted(set(touched_meeting_ids) | missing_ids | set(forced_ids)))
        if not target_ids:
            regroup_meeting_ids = ()
            return StageResult(
                summary={
                    "meeting_count": 0,
                    "scraped_meeting_count": 0,
                    "scraped_meeting_ids": (),
                    "utterance_count": 0,
                    "selected_worker_count": None,
                    "scrape_error_count": 0,
                    "member_mapped_count": 0,
                    "sample_errors": (),
                    "skipped_reason": "no touched, missing, forced, or retryable meetings",
                }
            )
        result = ingest_utterances(
            calibration_limit=max(len(target_ids), 1),
            meeting_ids=target_ids,
            allow_partial=True,
        )
        regroup_meeting_ids = tuple(result.scraped_meeting_ids)
        failures = tuple(
            DeadLetterDraft(
                source="minutes.html",
                stage="fetch",
                item_key=str(failure.mnts_id),
                payload={"mnts_id": failure.mnts_id},
                error=failure.error,
            )
            for failure in result.scrape_failures
        )
        return _stage_from_result(result, exclude=("scrape_failures",), dead_letters=failures)

    def run_session_groups() -> StageResult:
        if not regroup_meeting_ids:
            return StageResult(
                summary={
                    "meeting_count": 0,
                    "skipped_meeting_count": 0,
                    "group_count": 0,
                    "utterance_link_count": 0,
                    "skipped_reason": "no utterance changes to regroup",
                }
            )
        return _stage_from_result(ingest_session_groups(meeting_ids=regroup_meeting_ids))

    return (
        BackfillStage("retry_dead_letters", _run_dead_letter_retry),
        BackfillStage("members", run_members),
        BackfillStage("bills", run_bills),
        BackfillStage("votes", run_votes),
        BackfillStage("meetings", run_meetings),
        BackfillStage("utterances", run_utterances),
        BackfillStage("session_groups", run_session_groups),
        BackfillStage("validate_session_groups", lambda: _stage_from_result(validate_session_groups())),
        BackfillStage("sanity_check", lambda: _stage_from_result(run_sanity_check())),
        BackfillStage(
            "data_completeness",
            lambda: _stage_from_result(generate_data_completeness_report()),
        ),
        BackfillStage("migration_readiness", _run_migration_readiness),
    )


def _run_dead_letter_retry() -> StageResult:
    return _stage_from_result(retry_dead_letters())


def _run_migration_readiness() -> StageResult:
    return _stage_from_result(generate_migration_readiness_report())


def _stage_from_result(
    result: object,
    *,
    exclude: Sequence[str] = (),
    dead_letters: tuple[DeadLetterDraft, ...] = (),
) -> StageResult:
    raw = _summary_from_result(result, exclude=exclude)
    return StageResult(summary=raw, dead_letters=dead_letters)


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


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    return value
