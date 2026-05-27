"""Slice 14 — 증분 수집 planner 검증."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from congress_db.db import get_conn
from congress_db.incremental_plan import (
    CONGRESS_22_START,
    SourceCursor,
    load_source_cursors,
    plan_incremental_sync,
    plan_incremental_sync_from_db,
)
from congress_db.ingest_state import start_run, upsert_cursor


@pytest.fixture(autouse=True)
def clean_incremental_plan_state() -> None:
    _delete_test_state()
    yield
    _delete_test_state()


def _delete_test_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ingest_cursors WHERE source LIKE 'test.%'")
        cur.execute("DELETE FROM ingest_runs WHERE summary->>'test' = 'incremental_plan'")
        conn.commit()


def test_plan_uses_source_specific_cursors_and_overlap_windows() -> None:
    run_window_end = datetime(2026, 5, 27, 0, 0, tzinfo=UTC)
    cursors = {
        "bills": SourceCursor(
            source="bills",
            cursor_kind="propose_or_proc_dt",
            cursor_value=datetime(2026, 5, 20, tzinfo=UTC),
            overlap_days=30,
        ),
        "votes": SourceCursor(
            source="votes",
            cursor_kind="vote_date",
            cursor_value=datetime(2026, 5, 21, tzinfo=UTC),
            overlap_days=7,
        ),
    }

    plan = plan_incremental_sync(cursors, run_window_end=run_window_end)
    by_source = {source.source: source for source in plan.sources}

    assert by_source["members"].cursor_kind == "full_refresh"
    assert by_source["members"].window_start is None
    assert by_source["members"].window_end == run_window_end

    assert by_source["bills"].cursor_kind == "propose_or_proc_dt"
    assert by_source["bills"].window_start == datetime(2026, 4, 20, tzinfo=UTC)
    assert by_source["bills"].window_end == run_window_end

    assert by_source["votes"].cursor_kind == "vote_date"
    assert by_source["votes"].window_start == datetime(2026, 5, 14, tzinfo=UTC)
    assert by_source["votes"].window_end == run_window_end

    assert by_source["meetings"].cursor_kind == "conf_date"
    assert by_source["meetings"].window_start == CONGRESS_22_START
    assert by_source["meetings"].window_end == run_window_end

    assert by_source["bills"].cursor_advance_on_success.cursor_value == run_window_end
    assert by_source["votes"].cursor_advance_on_success.cursor_value == run_window_end
    assert by_source["meetings"].cursor_advance_on_success.cursor_value == run_window_end


def test_plan_dedupes_touched_meetings_for_dependent_stages() -> None:
    run_window_end = datetime(2026, 5, 27, 0, 0, tzinfo=UTC)

    plan = plan_incremental_sync(
        {},
        run_window_end=run_window_end,
        touched_meeting_ids=(920102, 920101, 920102),
    )
    by_source = {source.source: source for source in plan.sources}

    assert by_source["utterances"].cursor_kind == "meeting_id_set"
    assert by_source["utterances"].meeting_ids == (920101, 920102)
    assert by_source["utterances"].window_start is None
    assert by_source["session_groups"].cursor_kind == "meeting_id_set"
    assert by_source["session_groups"].meeting_ids == (920101, 920102)


def test_plan_loads_cursors_from_db() -> None:
    cursor_value = datetime(2026, 5, 20, tzinfo=UTC)
    run_window_end = datetime(2026, 5, 27, tzinfo=UTC)

    with get_conn() as conn:
        run_id = start_run(conn, mode="incremental", summary={"test": "incremental_plan"})
        upsert_cursor(
            conn,
            source="bills",
            cursor_kind="propose_or_proc_dt",
            cursor_value=cursor_value,
            updated_run_id=run_id,
            overlap_days=14,
        )
        cursors = load_source_cursors(conn)
        plan = plan_incremental_sync_from_db(
            conn,
            run_window_end=run_window_end,
            touched_meeting_ids=(1, 1, 2),
        )
        conn.rollback()

    assert cursors["bills"].cursor_value == cursor_value
    by_source = {source.source: source for source in plan.sources}
    assert by_source["bills"].window_start == cursor_value - timedelta(days=14)
    assert by_source["utterances"].meeting_ids == (1, 2)
