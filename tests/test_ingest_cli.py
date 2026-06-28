"""Official ingest CLI argument handling."""

from __future__ import annotations

from types import SimpleNamespace

from scripts import ingest as ingest_cli


def test_ingest_cli_passes_mode_to_run_ingest(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_run_ingest(*, mode: str):
        calls["mode"] = mode
        return SimpleNamespace(
            mode=mode,
            run_id=123,
            status="success",
            stage_summaries={},
            dead_letter_count=0,
        )

    monkeypatch.setattr(
        "sys.argv",
        [
            "ingest.py",
            "--mode",
            "incremental",
        ],
    )
    monkeypatch.setattr(ingest_cli, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(ingest_cli, "safe_print", lambda *_args, **_kwargs: None)

    ingest_cli.main()

    assert calls == {"mode": "incremental"}
