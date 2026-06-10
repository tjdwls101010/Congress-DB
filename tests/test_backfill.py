"""Slice 13 — 백필 orchestrator 검증."""

from __future__ import annotations

from typing import Any

import pytest

from congress_db.ingest.backfill import (
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    build_default_backfill_stages,
    load_utterance_target_meeting_ids,
    run_backfill,
)
import congress_db.ingest.backfill as backfill_module
from congress_db.core.db import get_conn


@pytest.fixture(autouse=True)
def clean_backfill_state() -> None:
    _delete_test_state()
    yield
    _delete_test_state()


def _delete_test_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM utterances WHERE meeting_id = ANY(%s)", ([930101, 930102],))
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = ANY(%s)", ([930101, 930102],))
        cur.execute("DELETE FROM meetings WHERE mnts_id = ANY(%s)", ([930101, 930102],))
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


def test_run_backfill_marks_run_failed_when_interrupted() -> None:
    def interrupting_stage() -> StageResult:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_backfill(
            stages=(BackfillStage("utterances", interrupting_stage),),
            run_metadata={"test": "backfill"},
        )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, error
            FROM ingest_runs
            WHERE summary->>'test' = 'backfill'
            ORDER BY id DESC
            LIMIT 1
            """
        )
        run = cur.fetchone()

    assert run == ("failed", "utterances: KeyboardInterrupt")


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
        "sanity_check",
        "data_completeness",
    ]

    for stage in stages:
        stage.run()

    assert calls["members"] == {}
    assert calls["bills"]["limit_pct"] == 1.0
    assert calls["bills"]["benchmark_sample_size"] == 1000
    assert calls["votes"]["limit_pct"] == 1.0
    assert calls["votes"]["benchmark_sample_size"] == 1000
    assert calls["votes"]["allow_partial"] is True
    assert calls["meetings"]["calibration_limit"] is None
    assert calls["meetings"]["benchmark_sample_size"] == 1000
    assert calls["utterances"]["meeting_ids"] == (920101, 920102)
    assert calls["utterances"]["benchmark_sample_size"] == 300
    assert calls["utterances"]["allow_partial"] is True


def test_default_backfill_skips_utterance_when_no_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_module, "load_utterance_target_meeting_ids", lambda: ())

    def unexpected_utterances(**kwargs: Any) -> dict[str, object]:
        raise AssertionError("utterance ingest should be skipped when there are no targets")

    stages = build_default_backfill_stages(
        ingest_members_fn=lambda **kwargs: {"stage": "members"},
        ingest_bills_fn=lambda **kwargs: {"stage": "bills"},
        ingest_votes_fn=lambda **kwargs: {"stage": "votes"},
        ingest_meetings_fn=lambda **kwargs: {"stage": "meetings"},
        ingest_utterances_fn=unexpected_utterances,
        run_sanity_check_fn=lambda **kwargs: {"stage": "sanity"},
        generate_data_completeness_report_fn=lambda **kwargs: {"stage": "completeness"},
        load_meeting_ids_fn=lambda: (),
    )

    by_name = {stage.name: stage for stage in stages}

    utterances = by_name["utterances"].run()

    assert utterances.summary["meeting_count"] == 0
    assert utterances.summary["skipped_reason"] == "no missing or explicitly targeted meetings"


def test_load_utterance_target_meeting_ids_only_returns_empty_meetings() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date)
            VALUES
                (930101, '이미 발언이 있는 회의', '상임위', '2026-05-01'),
                (930102, '발언 적재가 필요한 회의', '상임위', '2026-05-02')
            """
        )
        cur.execute(
            """
            INSERT INTO utterances (
                meeting_id, sequence, speaker_name, speaker_title, content, speaker_role
            )
            VALUES (930101, 1, '테스트', '위원', '이미 적재됨', '의원')
            """
        )
        conn.commit()

    targets = load_utterance_target_meeting_ids()

    assert 930102 in targets
    assert 930101 not in targets
    assert 52354 not in targets
    assert 52713 not in targets
