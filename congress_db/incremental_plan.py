"""증분 동기화 실행 계획."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping, Sequence

import psycopg

CONGRESS_22_START = datetime(2024, 5, 30, tzinfo=UTC)
DEFAULT_OVERLAP_DAYS = 30


@dataclass(frozen=True)
class SourceCursor:
    """DB에 저장된 source별 cursor."""

    source: str
    cursor_kind: str
    cursor_value: datetime | None
    overlap_days: int = DEFAULT_OVERLAP_DAYS


@dataclass(frozen=True)
class CursorAdvance:
    """source stage 성공 후에만 적용할 cursor 갱신 계획."""

    source: str
    cursor_kind: str
    cursor_value: datetime | None
    overlap_days: int = DEFAULT_OVERLAP_DAYS


@dataclass(frozen=True)
class SourcePlan:
    """한 source의 증분 실행 범위."""

    source: str
    cursor_kind: str
    window_start: datetime | None
    window_end: datetime | None
    meeting_ids: tuple[int, ...] = ()
    cursor_advance_on_success: CursorAdvance | None = None


@dataclass(frozen=True)
class IncrementalPlan:
    """한 incremental run의 source별 실행 계획."""

    sources: tuple[SourcePlan, ...]


def plan_incremental_sync(
    cursors: Mapping[str, SourceCursor],
    *,
    run_window_end: datetime,
    touched_meeting_ids: Sequence[int] = (),
) -> IncrementalPlan:
    """source별 cursor와 touched meeting으로 증분 실행 계획을 만든다."""
    touched = tuple(sorted(set(touched_meeting_ids)))
    return IncrementalPlan(
        sources=(
            _full_refresh_plan("members", run_window_end),
            _windowed_plan(
                "bills",
                "propose_or_proc_dt",
                cursors.get("bills"),
                run_window_end,
            ),
            _windowed_plan("votes", "vote_date", cursors.get("votes"), run_window_end),
            _windowed_plan("meetings", "conf_date", cursors.get("meetings"), run_window_end),
            _meeting_id_plan("utterances", touched, run_window_end),
            _meeting_id_plan("session_groups", touched, run_window_end),
        )
    )


def plan_incremental_sync_from_db(
    conn: psycopg.Connection,
    *,
    run_window_end: datetime,
    touched_meeting_ids: Sequence[int] = (),
) -> IncrementalPlan:
    """DB의 `ingest_cursors`를 읽어 증분 실행 계획을 만든다."""
    return plan_incremental_sync(
        load_source_cursors(conn),
        run_window_end=run_window_end,
        touched_meeting_ids=touched_meeting_ids,
    )


def load_source_cursors(conn: psycopg.Connection) -> dict[str, SourceCursor]:
    """현재 DB의 source별 cursor를 읽는다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source, cursor_kind, cursor_value, overlap_days
            FROM ingest_cursors
            ORDER BY source
            """
        )
        return {
            row[0]: SourceCursor(
                source=row[0],
                cursor_kind=row[1],
                cursor_value=row[2],
                overlap_days=row[3],
            )
            for row in cur.fetchall()
        }


def _full_refresh_plan(source: str, run_window_end: datetime) -> SourcePlan:
    cursor_kind = "full_refresh"
    return SourcePlan(
        source=source,
        cursor_kind=cursor_kind,
        window_start=None,
        window_end=run_window_end,
        cursor_advance_on_success=CursorAdvance(
            source=source,
            cursor_kind=cursor_kind,
            cursor_value=run_window_end,
            overlap_days=0,
        ),
    )


def _windowed_plan(
    source: str,
    cursor_kind: str,
    cursor: SourceCursor | None,
    run_window_end: datetime,
) -> SourcePlan:
    overlap_days = cursor.overlap_days if cursor else DEFAULT_OVERLAP_DAYS
    window_start = _window_start(cursor, overlap_days)
    return SourcePlan(
        source=source,
        cursor_kind=cursor_kind,
        window_start=window_start,
        window_end=run_window_end,
        cursor_advance_on_success=CursorAdvance(
            source=source,
            cursor_kind=cursor_kind,
            cursor_value=run_window_end,
            overlap_days=overlap_days,
        ),
    )


def _meeting_id_plan(
    source: str,
    meeting_ids: tuple[int, ...],
    run_window_end: datetime,
) -> SourcePlan:
    cursor_kind = "meeting_id_set"
    return SourcePlan(
        source=source,
        cursor_kind=cursor_kind,
        window_start=None,
        window_end=None,
        meeting_ids=meeting_ids,
        cursor_advance_on_success=CursorAdvance(
            source=source,
            cursor_kind=cursor_kind,
            cursor_value=run_window_end,
        ),
    )


def _window_start(cursor: SourceCursor | None, overlap_days: int) -> datetime:
    if cursor is None or cursor.cursor_value is None:
        return CONGRESS_22_START
    return cursor.cursor_value - timedelta(days=overlap_days)
