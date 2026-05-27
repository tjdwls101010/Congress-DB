"""Slice 13 — 백필 orchestrator 검증."""

from __future__ import annotations

from typing import Any

import pytest

from congress_db.backfill import (
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    build_default_backfill_stages,
    run_backfill,
)
from congress_db.db import get_conn


@pytest.fixture(autouse=True)
def clean_backfill_state() -> None:
    _delete_test_state()
    yield
    _delete_test_state()


def _delete_test_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM dead_letters WHERE source LIKE 'test.backfill.%'")
        cur.execute("DELETE FROM ingest_runs WHERE summary->>'test' = 'backfill'")
        conn.commit()


def test_run_backfill_records_stage_summaries_and_dead_letters(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[str] = []

    def stage(name: str, result: StageResult) -> BackfillStage:
        def run() -> StageResult:
            calls.append(name)
            return result

        return BackfillStage(name=name, run=run)

    result = run_backfill(
        stages=(
            stage("members", StageResult(summary={"fetched_count": 2, "upserted_count": 2})),
            stage(
                "utterances",
                StageResult(
                    summary={"meeting_count": 2, "scrape_error_count": 1},
                    dead_letters=(
                        DeadLetterDraft(
                            source="test.backfill.minutes",
                            stage="fetch",
                            item_key="920102",
                            payload={"mnts_id": 920102},
                            error="temporary block",
                        ),
                    ),
                ),
            ),
        ),
        run_metadata={"test": "backfill"},
    )

    assert calls == ["members", "utterances"]
    assert result.status == "degraded_success"
    assert result.dead_letter_count == 1

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mode, status, finished_at IS NOT NULL,
                   summary->>'test',
                   summary #>> '{stages,members,fetched_count}',
                   summary #>> '{stages,utterances,scrape_error_count}',
                   summary->>'dead_letter_count'
            FROM ingest_runs
            WHERE id = %s
            """,
            (result.run_id,),
        )
        run = cur.fetchone()
        cur.execute(
            """
            SELECT source, stage, item_key, payload->>'mnts_id', error, attempts, status
            FROM dead_letters
            WHERE run_id = %s
            """,
            (result.run_id,),
        )
        dead_letter = cur.fetchone()

    assert run == ("backfill", "degraded_success", True, "backfill", "2", "1", "1")
    assert dead_letter == (
        "test.backfill.minutes",
        "fetch",
        "920102",
        "920102",
        "temporary block",
        1,
        "pending",
    )
    output = capsys.readouterr().out
    assert "[backfill] stage=members start" in output
    assert "[backfill] stage=utterances done" in output


def test_run_backfill_marks_run_failed_when_required_stage_raises() -> None:
    calls: list[str] = []

    def ok_stage() -> StageResult:
        calls.append("members")
        return StageResult(summary={"fetched_count": 1})

    def failing_stage() -> StageResult:
        calls.append("bills")
        raise RuntimeError("bill list unavailable")

    with pytest.raises(RuntimeError, match="bill list unavailable"):
        run_backfill(
            stages=(
                BackfillStage("members", ok_stage),
                BackfillStage("bills", failing_stage),
            ),
            run_metadata={"test": "backfill"},
        )

    assert calls == ["members", "bills"]

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, error, summary #>> '{stages,members,fetched_count}'
            FROM ingest_runs
            WHERE summary->>'test' = 'backfill'
            ORDER BY id DESC
            LIMIT 1
            """
        )
        run = cur.fetchone()

    assert run == ("failed", "bills: bill list unavailable", "1")


def test_default_backfill_stages_use_full_load_parameters() -> None:
    calls: dict[str, dict[str, Any]] = {}

    def capture(name: str):
        def run(**kwargs: Any) -> dict[str, object]:
            calls[name] = kwargs
            return {"stage": name}

        return run

    stages = build_default_backfill_stages(
        ingest_members_fn=capture("members"),
        ingest_bills_fn=capture("bills"),
        ingest_votes_fn=capture("votes"),
        ingest_meetings_fn=capture("meetings"),
        ingest_utterances_fn=capture("utterances"),
        ingest_session_groups_fn=capture("session_groups"),
        validate_session_groups_fn=capture("validate_session_groups"),
        run_sanity_check_fn=capture("sanity_check"),
        generate_data_completeness_report_fn=capture("data_completeness"),
        load_meeting_ids_fn=lambda: (920101, 920102),
    )

    assert [stage.name for stage in stages] == [
        "members",
        "bills",
        "votes",
        "meetings",
        "utterances",
        "session_groups",
        "validate_session_groups",
        "sanity_check",
        "data_completeness",
    ]

    for stage in stages:
        stage.run()

    assert calls["members"] == {}
    assert calls["bills"]["limit_pct"] == 1.0
    assert calls["votes"]["limit_pct"] == 1.0
    assert calls["meetings"]["calibration_limit"] is None
    assert calls["utterances"]["meeting_ids"] == (920101, 920102)
    assert calls["utterances"]["allow_partial"] is True
    assert calls["session_groups"]["meeting_ids"] == (920101, 920102)
