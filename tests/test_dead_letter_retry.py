"""Slice 15 — dead letter 재처리 workflow 검증."""

from __future__ import annotations

import pytest

from congress_db.db import get_conn
from congress_db.dead_letter_retry import (
    DeadLetterItem,
    load_unresolved_dead_letters,
    retry_unresolved_dead_letters,
)
from congress_db.ingest_state import record_dead_letter, start_run


TEST_SOURCE = "test.retry.minutes"


@pytest.fixture(autouse=True)
def clean_retry_state() -> None:
    _delete_test_state()
    yield
    _delete_test_state()


def _delete_test_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM dead_letters WHERE source LIKE 'test.retry.%'")
        cur.execute("DELETE FROM ingest_runs WHERE summary->>'test' = 'dead_letter_retry'")
        conn.commit()


def _seed_dead_letter(item_key: str, *, attempts: int = 1, source: str = TEST_SOURCE) -> int:
    with get_conn() as conn:
        run_id = start_run(conn, mode="incremental", summary={"test": "dead_letter_retry"})
        dead_letter_id = record_dead_letter(
            conn,
            run_id=run_id,
            source=source,
            stage="fetch",
            item_key=item_key,
            payload={"mnts_id": int(item_key)},
            error="initial failure",
        )
        for attempt in range(1, attempts):
            record_dead_letter(
                conn,
                run_id=run_id,
                source=source,
                stage="fetch",
                item_key=item_key,
                payload={"mnts_id": int(item_key), "attempt": attempt},
                error=f"failure {attempt}",
            )
        conn.commit()
    return dead_letter_id


def test_load_unresolved_dead_letters_is_deterministic() -> None:
    first_id = _seed_dead_letter("920102")
    second_id = _seed_dead_letter("920103")
    blocked_id = _seed_dead_letter("920104")
    with get_conn() as conn:
        run_id = start_run(conn, mode="incremental", summary={"test": "dead_letter_retry"})
        record_dead_letter(
            conn,
            run_id=run_id,
            source=TEST_SOURCE,
            stage="fetch",
            item_key="920104",
            payload={"mnts_id": 920104},
            error="blocked earlier",
            status="blocked",
        )
        conn.commit()

    with get_conn() as conn:
        items = load_unresolved_dead_letters(conn, source_prefix="test.retry.")
        blocked_items = load_unresolved_dead_letters(
            conn,
            include_blocked=True,
            source_prefix="test.retry.",
        )

    selected = [item.id for item in items if item.source == TEST_SOURCE]
    assert selected[:2] == [first_id, second_id]
    assert blocked_id not in selected
    assert blocked_id in [item.id for item in blocked_items]


def test_retry_resolves_success_and_keeps_failed_item_pending(capsys: pytest.CaptureFixture[str]) -> None:
    success_id = _seed_dead_letter("920102")
    failed_id = _seed_dead_letter("920103")
    handled: list[int] = []

    def handler(item: DeadLetterItem) -> None:
        handled.append(item.id)
        if item.item_key == "920103":
            raise RuntimeError("still blocked")

    result = retry_unresolved_dead_letters(
        handlers={(TEST_SOURCE, "fetch"): handler},
        run_metadata={"test": "dead_letter_retry"},
        max_attempts=3,
        source_prefix="test.retry.",
    )

    assert handled == [success_id, failed_id]
    assert result.status == "degraded_success"
    assert result.resolved_count == 1
    assert result.failed_count == 1

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, attempts, error, resolved_at IS NOT NULL
            FROM dead_letters
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            ([success_id, failed_id],),
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT status, summary->>'resolved_count', summary->>'failed_count'
            FROM ingest_runs
            WHERE id = %s
            """,
            (result.run_id,),
        )
        run = cur.fetchone()

    assert rows == [
        (success_id, "resolved", 1, "initial failure", True),
        (failed_id, "pending", 2, "still blocked", False),
    ]
    assert run == ("degraded_success", "1", "1")
    output = capsys.readouterr().out
    assert "[dead-letter-retry] selected=2" in output
    assert "resolved=1 failed=1 blocked=0" in output


def test_retry_blocks_repeated_failures_and_missing_handlers() -> None:
    repeated_id = _seed_dead_letter("920104", attempts=2)
    missing_handler_id = _seed_dead_letter("920105", source="test.retry.unknown")

    def failing_handler(item: DeadLetterItem) -> None:
        raise RuntimeError(f"cannot retry {item.item_key}")

    result = retry_unresolved_dead_letters(
        handlers={(TEST_SOURCE, "fetch"): failing_handler},
        run_metadata={"test": "dead_letter_retry"},
        max_attempts=3,
        source_prefix="test.retry.",
        supported_sources={(TEST_SOURCE, "fetch")},
    )

    assert result.status == "blocked"
    assert result.blocked_count == 2

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, attempts, error
            FROM dead_letters
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            ([repeated_id, missing_handler_id],),
        )
        rows = cur.fetchall()

    assert rows == [
        (repeated_id, "blocked", 3, "cannot retry 920104"),
        (
            missing_handler_id,
            "blocked",
            2,
            "no retry handler for test.retry.unknown/fetch",
        ),
    ]
