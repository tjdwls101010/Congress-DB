"""Slice 2 RGR 4 — api_catalog → Markdown 변환 단위 테스트.

DB에 의존하지 않는 순수 함수 테스트. 입력 dict 리스트 → MD 문자열.
"""

from __future__ import annotations

from datetime import datetime, timezone

import scripts.render_api_catalog as render_api_catalog_script
from congress_db.api_catalog_render import render_pipeline_catalog_md


FIXED_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


def _row(
    endpoint: str,
    name: str = "테스트 API",
    *,
    has_22nd_data: bool | None = True,
    total_count_22nd: int | None = 100,
    status: str | None = "ok",
    usage_note: str = "테스트 적재",
    skip_reason: str | None = None,
) -> dict[str, object]:
    return {
        "inf_id": endpoint.upper(),
        "endpoint": endpoint,
        "name": name,
        "used_in_pipeline": True,
        "usage_note": usage_note,
        "status": status,
        "has_22nd_data": has_22nd_data,
        "total_count_22nd": total_count_22nd,
        "skip_reason": skip_reason,
    }


def test_renders_header_and_generated_timestamp() -> None:
    md = render_pipeline_catalog_md([_row("foo")], now=FIXED_NOW)

    assert "# API Catalog" in md
    assert "_Generated: 2026-05-26T12:00:00+00:00_" in md
    assert "ADR 0001" in md


def test_renders_one_row_per_endpoint() -> None:
    rows = [_row("a"), _row("b"), _row("c")]
    md = render_pipeline_catalog_md(rows, now=FIXED_NOW)

    assert md.count("| `a`") == 1
    assert md.count("| `b`") == 1
    assert md.count("| `c`") == 1


def test_ok_row_shows_checkmark_and_thousands_separator() -> None:
    md = render_pipeline_catalog_md(
        [_row("foo", has_22nd_data=True, total_count_22nd=17286, status="ok")],
        now=FIXED_NOW,
    )

    assert "| ✓ | 17,286 |" in md


def test_no_data_row_shows_dash() -> None:
    md = render_pipeline_catalog_md(
        [_row("foo", has_22nd_data=None, total_count_22nd=None, status="no_data")],
        now=FIXED_NOW,
    )

    assert "| — | — |" in md
    assert "no_data" in md


def test_skip_reason_appears_in_notes_section() -> None:
    md = render_pipeline_catalog_md(
        [
            _row("ok_one"),
            _row("bad_one", status="error", skip_reason="필수 BILL_ID 부재"),
        ],
        now=FIXED_NOW,
    )

    assert "## Notes" in md
    assert "`bad_one`: 필수 BILL_ID 부재" in md
    # OK row는 Notes에 안 들어감
    assert "`ok_one`:" not in md.split("## Notes")[1]


def test_no_notes_section_when_no_skip_reasons() -> None:
    md = render_pipeline_catalog_md([_row("foo"), _row("bar")], now=FIXED_NOW)

    assert "## Notes" not in md


def test_pipe_in_usage_note_is_escaped() -> None:
    md = render_pipeline_catalog_md(
        [_row("foo", usage_note="A | B")],
        now=FIXED_NOW,
    )

    # | 가 \\| 로 escape되어야 markdown 테이블이 깨지지 않음
    assert "A \\| B" in md


def test_empty_catalog_mentions_reseed_needed() -> None:
    md = render_pipeline_catalog_md([], now=FIXED_NOW)

    assert "api_catalog 비어 있음 — 재시드 필요" in md


def test_render_catalog_cli_seeds_before_fetch(monkeypatch, tmp_path) -> None:
    calls: list[object] = []

    monkeypatch.setattr(render_api_catalog_script, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(render_api_catalog_script, "OUTPUT", tmp_path / "API-CATALOG.md")
    monkeypatch.setattr(
        render_api_catalog_script,
        "seed_pipeline_endpoints",
        lambda: calls.append("seed") or 2,
        raising=False,
    )
    monkeypatch.setattr(
        render_api_catalog_script,
        "fetch_pipeline_catalog_rows",
        lambda: calls.append("fetch") or [_row("a"), _row("b")],
    )
    monkeypatch.setattr(
        render_api_catalog_script,
        "render_pipeline_catalog_md",
        lambda rows: calls.append(("render", len(rows))) or "catalog md\n",
    )

    render_api_catalog_script.main()

    assert calls == ["seed", "fetch", ("render", 2)]
    assert (tmp_path / "API-CATALOG.md").read_text() == "catalog md\n"
