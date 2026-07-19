"""공식 단일 수집 명령 검증."""

from __future__ import annotations

import congress_db.ingest.ingest_command as ingest_command
from congress_db.ingest.ingest_command import (
    _compact_resumed_stage_summary,
    _is_resumable_stage_summary_healthy,
    build_incremental_stages,
    decide_ingest_mode,
)


def test_incremental_stages_include_bill_final_outcomes_after_votes() -> None:
    names = [stage.name for stage in build_incremental_stages()]
    assert "bill_final_outcomes" in names
    assert names.index("bill_final_outcomes") == names.index("votes") + 1
    assert names.index("bill_final_outcomes") < names.index("sanity_check")


def test_decide_ingest_mode_uses_backfill_until_successful_baseline_and_cursors() -> None:
    assert (
        decide_ingest_mode("auto", successful_backfill=False, required_cursors=False)
        == "backfill"
    )
    assert (
        decide_ingest_mode("auto", successful_backfill=True, required_cursors=False)
        == "backfill"
    )
    assert (
        decide_ingest_mode("auto", successful_backfill=True, required_cursors=True)
        == "incremental"
    )
    assert (
        decide_ingest_mode("incremental", successful_backfill=False, required_cursors=False)
        == "incremental"
    )


def test_incremental_stages_scope_bills_and_votes_to_missing(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(ingest_command, "retry_dead_letters", lambda: {"retried": 0})
    monkeypatch.setattr(ingest_command, "ingest_members", lambda: {"stage": "members"})
    monkeypatch.setattr(
        ingest_command,
        "backfill_bill_final_outcomes",
        lambda: {"stage": "bill_final_outcomes"},
    )

    def fake_bills(**kwargs):
        calls["bills_kwargs"] = kwargs
        return {"stage": "bills"}

    def fake_votes(**kwargs):
        calls["votes_kwargs"] = kwargs
        return {"stage": "votes"}

    monkeypatch.setattr(ingest_command, "ingest_bills", fake_bills)
    monkeypatch.setattr(ingest_command, "ingest_votes", fake_votes)
    monkeypatch.setattr(ingest_command, "run_sanity_check", lambda: {"stage": "sanity"})
    monkeypatch.setattr(
        ingest_command,
        "generate_data_completeness_report",
        lambda: {"stage": "completeness"},
    )
    monkeypatch.setattr(
        ingest_command,
        "generate_migration_readiness_report",
        lambda: {"stage": "readiness"},
    )

    for stage in build_incremental_stages():
        stage.run()

    assert calls["bills_kwargs"]["summary_fetch_mode"] == "missing"
    assert calls["bills_kwargs"]["summary_worker_count"] > 0
    assert calls["votes_kwargs"]["vote_row_fetch_mode"] == "missing"
    assert calls["votes_kwargs"]["vote_row_worker_count"] > 0


def test_incremental_stages_cap_explicit_worker_counts(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setenv("CONGRESS_DB_HTTP_CONCURRENCY_LIMIT", "7")
    monkeypatch.setattr(ingest_command, "retry_dead_letters", lambda: {"retried": 0})
    monkeypatch.setattr(ingest_command, "ingest_members", lambda: {"stage": "members"})
    monkeypatch.setattr(
        ingest_command,
        "backfill_bill_final_outcomes",
        lambda: {"stage": "bill_final_outcomes"},
    )
    monkeypatch.setattr(
        ingest_command,
        "ingest_bills",
        lambda **kwargs: calls.__setitem__("bills_kwargs", kwargs) or {"stage": "bills"},
    )
    monkeypatch.setattr(
        ingest_command,
        "ingest_votes",
        lambda **kwargs: calls.__setitem__("votes_kwargs", kwargs) or {"stage": "votes"},
    )
    monkeypatch.setattr(ingest_command, "run_sanity_check", lambda: {"stage": "sanity"})
    monkeypatch.setattr(
        ingest_command,
        "generate_data_completeness_report",
        lambda: {"stage": "completeness"},
    )
    monkeypatch.setattr(
        ingest_command,
        "generate_migration_readiness_report",
        lambda: {"stage": "readiness"},
    )

    for stage in build_incremental_stages():
        stage.run()

    assert calls["bills_kwargs"]["summary_worker_count"] == 7
    assert calls["votes_kwargs"]["vote_row_worker_count"] == 7


def test_resumable_stage_summary_health_checks_completed_ingest_stages() -> None:
    assert _is_resumable_stage_summary_healthy(
        "bills",
        {"fetched_count": 100, "target_count": 100, "summary_error_count": 0},
    )
    assert not _is_resumable_stage_summary_healthy(
        "bills",
        {"fetched_count": 100, "target_count": 100, "summary_error_count": 1},
    )
    assert _is_resumable_stage_summary_healthy(
        "votes",
        {"vote_bill_count": 10, "target_bill_count": 10, "failed_vote_bill_count": 0},
    )
    assert not _is_resumable_stage_summary_healthy(
        "votes",
        {"vote_bill_count": 10, "target_bill_count": 10, "failed_vote_bill_count": 1},
    )


def test_compact_resumed_stage_summary_replaces_large_sequences_with_counts() -> None:
    compacted = _compact_resumed_stage_summary(
        {"new_bill_ids": list(range(30)), "target_count": 30}
    )

    assert compacted["new_bill_ids"] == {"count": 30, "sample": [0, 1, 2, 3, 4]}
    assert compacted["target_count"] == 30
