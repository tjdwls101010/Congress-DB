"""Documentation structure contract."""

from pathlib import Path

import scripts.render_api_catalog as render_api_catalog_script
from congress_db.ops.data_completeness import DEFAULT_DATA_COMPLETENESS_REPORT
from congress_db.ingest.ingest_bills import DEFAULT_BENCHMARK_OUTPUT
from congress_db.ingest.ingest_votes import DEFAULT_VOTE_BENCHMARK_OUTPUT
from congress_db.ops.migration_readiness import DEFAULT_MIGRATION_READINESS_REPORT
from congress_db.ops.sanity_check import DEFAULT_SANITY_REPORT


def test_generated_report_defaults_write_to_docs_ops() -> None:
    expected = {
        Path("docs/ops/API-CATALOG.md"),
        Path("docs/ops/DATA-COMPLETENESS.md"),
        Path("docs/ops/MIGRATION-READINESS.md"),
        Path("docs/ops/PARALLEL-BENCHMARK.md"),
        Path("docs/ops/SANITY-CHECK.md"),
        Path("docs/ops/VOTES-PARALLEL-BENCHMARK.md"),
    }

    actual = {
        DEFAULT_DATA_COMPLETENESS_REPORT,
        DEFAULT_BENCHMARK_OUTPUT,
        DEFAULT_MIGRATION_READINESS_REPORT,
        DEFAULT_SANITY_REPORT,
        DEFAULT_VOTE_BENCHMARK_OUTPUT,
        render_api_catalog_script.OUTPUT.relative_to(render_api_catalog_script.REPO_ROOT),
    }

    assert actual == expected


def test_per_file_adrs_absorbed_into_decisions_log() -> None:
    assert not (Path("docs") / "adr").exists()
    decisions = Path("docs/design/DECISIONS.md").read_text(encoding="utf-8")

    for adr_id in range(1, 10):
        assert f"ADR-{adr_id:04d}" in decisions


def test_current_design_docs_are_direct_sql_centered_not_sdk_centered() -> None:
    assert not (Path("docs") / "CONGRESS-SDK-CODEX-BRIEF.md").exists()

    for path in (
        Path("CONTEXT.md"),
        Path("docs/design/PRD.md"),
        Path("docs/design/IA.md"),
        Path("docs/design/ERD.md"),
        Path("docs/design/DB-QUERY-GUIDE.md"),
    ):
        text = path.read_text(encoding="utf-8")
        assert "검색 API/SDK" not in text
        assert "congress-sdk" not in text
        assert "Congress-SDK" not in text
