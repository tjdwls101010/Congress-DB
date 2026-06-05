"""공식 단일 수집 명령 검증."""

from __future__ import annotations

from types import SimpleNamespace

import congress_db.ingest_command as ingest_command
from congress_db.ingest_command import (
    _compact_resumed_stage_summary,
    _is_resumable_stage_summary_healthy,
    build_incremental_stages,
    decide_ingest_mode,
)


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


def test_incremental_stages_scope_utterances_to_touched_meetings(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(ingest_command, "retry_dead_letters", lambda: {"retried": 0})
    monkeypatch.setattr(ingest_command, "ingest_members", lambda: {"stage": "members"})

    def fake_bills(**kwargs):
        calls["bills_kwargs"] = kwargs
        return {"stage": "bills"}

    def fake_votes(**kwargs):
        calls["votes_kwargs"] = kwargs
        return {"stage": "votes"}

    monkeypatch.setattr(ingest_command, "ingest_bills", fake_bills)
    monkeypatch.setattr(ingest_command, "ingest_votes", fake_votes)
    monkeypatch.setattr(
        ingest_command,
        "ingest_meetings",
        lambda **kwargs: (
            calls.__setitem__("meetings_kwargs", kwargs)
            or SimpleNamespace(
                new_meeting_ids=(920101,),
                changed_meeting_ids=(920102,),
                stale_meeting_ids=(),
                vconfbill_failures=(),
            )
        ),
    )
    monkeypatch.setattr(
        ingest_command,
        "load_utterance_target_meeting_ids",
        lambda: (920103,),
    )

    def fake_utterances(**kwargs):
        calls["utterances_kwargs"] = kwargs
        calls["utterance_meeting_ids"] = kwargs["meeting_ids"]
        return SimpleNamespace(
            meeting_count=len(kwargs["meeting_ids"]),
            scraped_meeting_count=len(kwargs["meeting_ids"]),
            scraped_meeting_ids=tuple(kwargs["meeting_ids"]),
            utterance_count=10,
            selected_worker_count=2,
            scrape_error_count=0,
            member_mapped_count=5,
            sample_errors=(),
            scrape_failures=(),
        )

    monkeypatch.setattr(ingest_command, "ingest_utterances", fake_utterances)
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

    for stage in build_incremental_stages(force_meeting_ids=(920104,)):
        stage.run()

    assert calls["utterance_meeting_ids"] == (920101, 920102, 920103, 920104)
    assert calls["bills_kwargs"]["summary_fetch_mode"] == "missing"
    assert calls["bills_kwargs"]["summary_worker_count"] > 0
    assert calls["votes_kwargs"]["vote_row_fetch_mode"] == "missing"
    assert calls["votes_kwargs"]["vote_row_worker_count"] > 0
    assert calls["meetings_kwargs"]["vconfbill_worker_count"] > 0
    assert calls["meetings_kwargs"]["vconfbill_fetch_mode"] == "missing"
    assert calls["meetings_kwargs"]["vconfbill_force_meeting_ids"] == (920104,)
    assert calls["meetings_kwargs"]["allow_partial_vconfbill"] is True
    assert calls["utterances_kwargs"]["scrape_worker_count"] > 0


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
        {"new_meeting_ids": list(range(30)), "target_count": 30}
    )

    assert compacted["new_meeting_ids"] == {"count": 30, "sample": [0, 1, 2, 3, 4]}
    assert compacted["target_count"] == 30
