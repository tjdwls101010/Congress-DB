"""Slice 12 — 수집 운영 상태 Interface 검증."""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from congress_db.core.db import get_conn
from congress_db.ingest.ingest_state import (
    finish_run,
    record_dead_letter,
    resolve_dead_letter,
    start_run,
    upsert_cursor,
)


TEST_SOURCE = "test.ingest_state"


@pytest.fixture(autouse=True)
def clean_ingest_state() -> None:
    _delete_test_state()
    yield
    _delete_test_state()


def _delete_test_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ingest_cursors WHERE source LIKE 'test.%'")
        cur.execute("DELETE FROM dead_letters WHERE source LIKE 'test.%'")
        cur.execute("DELETE FROM ingest_runs WHERE summary->>'test' = 'ingest_state'")
        conn.commit()


def test_ingest_state_tracks_run_cursor_and_dead_letter_lifecycle() -> None:
    cursor_value = datetime(2026, 5, 27, 0, 0, tzinfo=UTC)

    with get_conn() as conn:
        run_id = start_run(
            conn,
            mode="incremental",
            overlap_days=30,
            window_start=datetime(2026, 4, 27, tzinfo=UTC),
            window_end=cursor_value,
            summary={"test": "ingest_state", "stage": "started"},
        )
        upsert_cursor(
            conn,
            source=TEST_SOURCE,
            cursor_kind="propose_or_proc_dt",
            cursor_value=cursor_value,
            updated_run_id=run_id,
            overlap_days=30,
        )

        first_dead_letter_id = record_dead_letter(
            conn,
            run_id=run_id,
            source=TEST_SOURCE,
            stage="fetch",
            item_key="BILL-1",
            payload={"bill_no": "BILL-1"},
            error="temporary timeout",
        )
        same_dead_letter_id = record_dead_letter(
            conn,
            run_id=run_id,
            source=TEST_SOURCE,
            stage="fetch",
            item_key="BILL-1",
            payload={"bill_no": "BILL-1", "retry": 1},
            error="timeout again",
        )
        assert same_dead_letter_id == first_dead_letter_id

        assert resolve_dead_letter(conn, first_dead_letter_id) is True
        new_dead_letter_id = record_dead_letter(
            conn,
            run_id=run_id,
            source=TEST_SOURCE,
            stage="fetch",
            item_key="BILL-1",
            payload={"bill_no": "BILL-1", "retry": 2},
            error="failed after resolution",
        )
        assert new_dead_letter_id != first_dead_letter_id

        finish_run(
            conn,
            run_id,
            status="degraded_success",
            summary={"test": "ingest_state", "dead_letters": 1},
            error="one item failed",
        )
        conn.commit()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mode, status, finished_at IS NOT NULL, overlap_days,
                   summary->>'dead_letters', error
            FROM ingest_runs
            WHERE id = %s
            """,
            (run_id,),
        )
        run = cur.fetchone()

        cur.execute(
            """
            SELECT cursor_kind, cursor_value, overlap_days, updated_run_id
            FROM ingest_cursors
            WHERE source = %s
            """,
            (TEST_SOURCE,),
        )
        cursor = cur.fetchone()

        cur.execute(
            """
            SELECT id, status, attempts, error, payload->>'retry',
                   first_failed_at <= last_failed_at, resolved_at IS NOT NULL
            FROM dead_letters
            WHERE source = %s
            ORDER BY id
            """,
            (TEST_SOURCE,),
        )
        dead_letters = cur.fetchall()

    assert run == (
        "incremental",
        "degraded_success",
        True,
        30,
        "1",
        "one item failed",
    )
    assert cursor == ("propose_or_proc_dt", cursor_value, 30, run_id)
    assert dead_letters == [
        (first_dead_letter_id, "resolved", 2, "timeout again", "1", True, True),
        (new_dead_letter_id, "pending", 1, "failed after resolution", "2", True, False),
    ]


@pytest.mark.parametrize(
    "sql",
    [
        """
        INSERT INTO ingest_runs (mode, status, summary)
        VALUES ('wrong', 'running', '{"test":"ingest_state"}')
        """,
        """
        INSERT INTO ingest_runs (mode, status, summary)
        VALUES ('backfill', 'wrong', '{"test":"ingest_state"}')
        """,
    ],
)
def test_ingest_runs_reject_invalid_mode_or_status(sql: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(sql)
        conn.rollback()


def test_dead_letters_reject_invalid_status() -> None:
    with get_conn() as conn:
        run_id = start_run(
            conn,
            mode="dead_letter_retry",
            summary={"test": "ingest_state"},
        )
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    """
                    INSERT INTO dead_letters
                        (run_id, source, stage, item_key, error, status)
                    VALUES (%s, %s, 'fetch', 'bad-status', 'boom', 'wrong')
                    """,
                    (run_id, TEST_SOURCE),
                )
        conn.rollback()


def test_ingest_state_indexes_exist() -> None:
    expected = {
        "idx_ingest_runs_mode_started",
        "idx_ingest_runs_status_started",
        "idx_ingest_cursors_updated_run",
        "idx_dead_letters_run_id",
        "idx_dead_letters_status_last_failed",
        "idx_dead_letters_source_item",
        "idx_dead_letters_unresolved_unique",
    }
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = ANY(%s)
            """,
            (list(expected),),
        )
        found = {row[0] for row in cur.fetchall()}

    assert found == expected
