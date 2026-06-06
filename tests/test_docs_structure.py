"""Documentation structure contract."""

from pathlib import Path

import scripts.render_api_catalog as render_api_catalog_script
from congress_db.data_completeness import DEFAULT_DATA_COMPLETENESS_REPORT
from congress_db.ingest_bills import DEFAULT_BENCHMARK_OUTPUT
from congress_db.ingest_meetings import DEFAULT_MEETINGS_BENCHMARK_OUTPUT
from congress_db.ingest_utterances import DEFAULT_SCRAPE_BENCHMARK_OUTPUT
from congress_db.ingest_votes import DEFAULT_VOTE_BENCHMARK_OUTPUT
from congress_db.migration_readiness import DEFAULT_MIGRATION_READINESS_REPORT
from congress_db.sanity_check import DEFAULT_SANITY_REPORT
from congress_db.validate_minutes_dom import DEFAULT_DOM_VALIDATION_OUTPUT


def test_generated_report_defaults_write_to_docs_ops() -> None:
    expected = {
        Path("docs/ops/API-CATALOG.md"),
        Path("docs/ops/DATA-COMPLETENESS.md"),
        Path("docs/ops/MEETINGS-PARALLEL-BENCHMARK.md"),
        Path("docs/ops/MIGRATION-READINESS.md"),
        Path("docs/ops/MINUTES-DOM-VALIDATION.md"),
        Path("docs/ops/PARALLEL-BENCHMARK.md"),
        Path("docs/ops/SANITY-CHECK.md"),
        Path("docs/ops/VOTES-PARALLEL-BENCHMARK.md"),
    }

    actual = {
        DEFAULT_DATA_COMPLETENESS_REPORT,
        DEFAULT_BENCHMARK_OUTPUT,
        DEFAULT_MEETINGS_BENCHMARK_OUTPUT,
        DEFAULT_MIGRATION_READINESS_REPORT,
        DEFAULT_DOM_VALIDATION_OUTPUT,
        DEFAULT_SCRAPE_BENCHMARK_OUTPUT,
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
