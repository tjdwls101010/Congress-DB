"""dead letter 재시도 orchestration 검증."""

from __future__ import annotations

import pytest

from congress_db.core.db import get_conn
from congress_db.ingest.dead_letter_retry import (
    DeadLetter,
    default_retry_handlers,
    retry_dead_letters,
)
from congress_db.ingest.ingest_state import record_dead_letter, start_run


TEST_SOURCE = "test.retry.minutes"


@pytest.fixture(autouse=True)
def clean_retry_state() -> None:
    _delete_test_state()
    yield
    _delete_test_state()


def _delete_test_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM dead_letters WHERE source = %s", (TEST_SOURCE,))
        cur.execute("DELETE FROM ingest_runs WHERE summary->>'test' = 'dead_letter_retry'")
        conn.commit()


def test_retry_dead_letters_resolves_successful_handler() -> None:
    seen: list[DeadLetter] = []

    with get_conn() as conn:
        run_id = start_run(conn, mode="dead_letter_retry", summary={"test": "dead_letter_retry"})
        dead_letter_id = record_dead_letter(
            conn,
            run_id=run_id,
            source=TEST_SOURCE,
            stage="fetch",
            item_key="920101",
            payload={"mnts_id": 920101},
            error="temporary failure",
        )
        conn.commit()

    result = retry_dead_letters(
        handlers={
            (TEST_SOURCE, "fetch"): lambda dead_letter: seen.append(dead_letter) is None or True,
        },
        source_prefix=TEST_SOURCE,
    )

    assert result.unresolved_count == 1
    assert result.attempted_count == 1
    assert result.resolved_count == 1
    assert result.failed_count == 0
    assert seen[0].item_key == "920101"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, attempts, resolved_at IS NOT NULL
            FROM dead_letters
            WHERE id = %s
            """,
            (dead_letter_id,),
        )
        row = cur.fetchone()

    assert row == ("resolved", 2, True)


def test_retry_dead_letters_leaves_unhandled_items_pending() -> None:
    with get_conn() as conn:
        run_id = start_run(conn, mode="dead_letter_retry", summary={"test": "dead_letter_retry"})
        dead_letter_id = record_dead_letter(
            conn,
            run_id=run_id,
            source=TEST_SOURCE,
            stage="fetch",
            item_key="920102",
            payload={"mnts_id": 920102},
            error="temporary failure",
        )
        conn.commit()

    result = retry_dead_letters(handlers={}, source_prefix=TEST_SOURCE)

    assert result.unresolved_count == 1
    assert result.attempted_count == 0
    assert result.unhandled_count == 1

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, attempts FROM dead_letters WHERE id = %s", (dead_letter_id,))
        row = cur.fetchone()

    assert row == ("pending", 1)


def test_default_retry_handlers_cover_all_ingest_dead_letter_sources() -> None:
    assert set(default_retry_handlers()) == {
        ("minutes.html", "fetch"),
        ("bills.summary", "fetch"),
        ("votes.rows", "fetch"),
        ("meeting_bills.vconfbill", "fetch"),
    }
