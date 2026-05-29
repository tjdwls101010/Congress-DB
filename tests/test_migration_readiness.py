"""Slice 16 — Supabase migration readiness report 검증."""

from __future__ import annotations

from pathlib import Path

import pytest

from congress_db.db import get_conn
from congress_db.ingest_state import finish_run, record_dead_letter, start_run
from congress_db.migration_readiness import (
    generate_migration_readiness_report,
)


TEST_MEMBER = "TEST_READY_MEMBER"
TEST_MEETING = 970101


@pytest.fixture(autouse=True)
def clean_readiness_rows() -> None:
    parked_dead_letters = _park_non_test_dead_letters()
    _delete_rows()
    yield
    _delete_rows()
    _restore_dead_letters(parked_dead_letters)


def _delete_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM dead_letters WHERE source LIKE 'test.readiness.%'")
        cur.execute("DELETE FROM ingest_runs WHERE summary->>'test' = 'migration_readiness'")
        cur.execute("UPDATE utterances SET session_group_id = NULL WHERE meeting_id = %s", (TEST_MEETING,))
        cur.execute("DELETE FROM session_groups WHERE meeting_id = %s", (TEST_MEETING,))
        cur.execute("DELETE FROM utterances WHERE meeting_id = %s", (TEST_MEETING,))
        cur.execute("DELETE FROM meetings WHERE mnts_id = %s", (TEST_MEETING,))
        cur.execute("DELETE FROM members WHERE mona_cd = %s", (TEST_MEMBER,))
        conn.commit()


def _park_non_test_dead_letters() -> list[tuple[int, str, object]]:
    """로컬 백필 실패 기록이 readiness 단위 테스트를 오염시키지 않게 잠시 숨긴다."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, resolved_at
            FROM dead_letters
            WHERE source NOT LIKE 'test.readiness.%'
              AND status IN ('pending', 'retrying', 'blocked')
            """
        )
        rows = cur.fetchall()
        if rows:
            cur.execute(
                """
                UPDATE dead_letters
                SET status = 'ignored', resolved_at = now()
                WHERE id = ANY(%s)
                """,
                ([row[0] for row in rows],),
            )
        conn.commit()
    return rows


def _restore_dead_letters(rows: list[tuple[int, str, object]]) -> None:
    if not rows:
        return
    with get_conn() as conn, conn.cursor() as cur:
        for dead_letter_id, status, resolved_at in rows:
            cur.execute(
                """
                UPDATE dead_letters
                SET status = %s, resolved_at = %s
                WHERE id = %s
                """,
                (status, resolved_at, dead_letter_id),
            )
        conn.commit()


def _complete_summary() -> dict[str, object]:
    return {
        "test": "migration_readiness",
        "stages": {
            "sanity_check": {
                "sections": [
                    {"key": "S1"},
                    {"key": "S2"},
                    {"key": "S3"},
                    {"key": "S4a"},
                    {"key": "S4b"},
                    {"key": "S5"},
                    {"key": "S6"},
                    {"key": "S7"},
                ]
            },
            "data_completeness": {
                "metrics": [
                    {
                        "name": "vote_created_bill_gaps",
                        "value": 0,
                        "interpretation": "accepted",
                    }
                ]
            },
        },
    }


def _create_backfill_run(*, status: str = "success", summary: dict[str, object] | None = None) -> int:
    with get_conn() as conn:
        run_id = start_run(
            conn,
            mode="backfill",
            summary={"test": "migration_readiness"},
        )
        finish_run(
            conn,
            run_id,
            status=status,
            summary=summary or _complete_summary(),
        )
        conn.commit()
    return run_id


def test_readiness_report_returns_ready_when_required_signals_are_clear(tmp_path: Path) -> None:
    _create_backfill_run()

    report = generate_migration_readiness_report(output_path=tmp_path / "ready.md")

    assert report.recommendation == "ready_for_human_review"
    assert report.blockers == ()
    assert "ready_for_human_review" in (tmp_path / "ready.md").read_text()


def test_readiness_report_blocks_on_unresolved_dead_letters(tmp_path: Path) -> None:
    run_id = _create_backfill_run()
    with get_conn() as conn:
        record_dead_letter(
            conn,
            run_id=run_id,
            source="test.readiness.minutes",
            stage="fetch",
            item_key="970101",
            payload={"mnts_id": 970101},
            error="still failing",
        )
        conn.commit()

    report = generate_migration_readiness_report(output_path=tmp_path / "not-ready.md")

    assert report.recommendation == "not_ready_for_human_review"
    assert any("unresolved dead letters" in blocker for blocker in report.blockers)
    assert report.dead_letter_counts[0]["count"] == 1


def test_readiness_report_blocks_on_session_group_integrity_errors(tmp_path: Path) -> None:
    _create_backfill_run()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO members (mona_cd, hg_nm) VALUES (%s, '테스트')",
            (TEST_MEMBER,),
        )
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date)
            VALUES (%s, '테스트 위원회', '상임위', '2026-05-20')
            """,
            (TEST_MEETING,),
        )
        cur.execute(
            """
            INSERT INTO utterances
                (meeting_id, sequence, speaker_name, speaker_title, speaker_mona_cd, content)
            VALUES (%s, 1, '테스트', '위원', %s, '발언')
            """,
            (TEST_MEETING, TEST_MEMBER),
        )
        cur.execute(
            """
            INSERT INTO session_groups (
                meeting_id, questioner_mona_cd, respondents,
                seq_start, seq_end, utterance_count, total_chars
            )
            VALUES (%s, %s, '[{"name":"답변자","title":"장관"}]', 1, 1, 99, 99)
            RETURNING id
            """,
            (TEST_MEETING, TEST_MEMBER),
        )
        session_group_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE utterances SET session_group_id = %s WHERE meeting_id = %s",
            (session_group_id, TEST_MEETING),
        )
        conn.commit()

    report = generate_migration_readiness_report(output_path=tmp_path / "integrity.md")

    assert report.recommendation == "not_ready_for_human_review"
    assert report.session_group_integrity_error_count > 0
    assert any("session group integrity" in blocker for blocker in report.blockers)


def test_readiness_report_blocks_when_required_stage_signals_are_unavailable(tmp_path: Path) -> None:
    _create_backfill_run(summary={"test": "migration_readiness", "stages": {}})

    report = generate_migration_readiness_report(output_path=tmp_path / "missing.md")

    assert report.recommendation == "not_ready_for_human_review"
    assert "sanity_check signal unavailable" in report.blockers
    assert "data_completeness signal unavailable" in report.blockers
