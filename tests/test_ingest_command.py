"""공식 단일 수집 명령 검증."""

from __future__ import annotations

from types import SimpleNamespace

import congress_db.ingest_command as ingest_command
from congress_db.ingest_command import build_incremental_stages, decide_ingest_mode


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


def test_incremental_stages_scope_utterances_and_session_groups_to_touched_meetings(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(ingest_command, "retry_dead_letters", lambda: {"retried": 0})
    monkeypatch.setattr(ingest_command, "ingest_members", lambda: {"stage": "members"})
    monkeypatch.setattr(ingest_command, "ingest_bills", lambda **kwargs: {"stage": "bills"})
    monkeypatch.setattr(ingest_command, "ingest_votes", lambda **kwargs: {"stage": "votes"})
    monkeypatch.setattr(
        ingest_command,
        "ingest_meetings",
        lambda **kwargs: SimpleNamespace(
            new_meeting_ids=(920101,),
            changed_meeting_ids=(920102,),
            stale_meeting_ids=(),
        ),
    )
    monkeypatch.setattr(
        ingest_command,
        "load_utterance_target_meeting_ids",
        lambda: (920103,),
    )

    def fake_utterances(**kwargs):
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

    def fake_session_groups(**kwargs):
        calls["session_group_meeting_ids"] = kwargs["meeting_ids"]
        return {"meeting_count": len(kwargs["meeting_ids"])}

    monkeypatch.setattr(ingest_command, "ingest_utterances", fake_utterances)
    monkeypatch.setattr(ingest_command, "ingest_session_groups", fake_session_groups)
    monkeypatch.setattr(ingest_command, "validate_session_groups", lambda: {"stage": "validate"})
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
    assert calls["session_group_meeting_ids"] == (920101, 920102, 920103, 920104)
