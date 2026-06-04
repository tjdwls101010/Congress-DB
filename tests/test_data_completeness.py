"""10% data completeness report behavior."""

from congress_db.data_completeness import (
    CompletenessReport,
    Metric,
    SampleTable,
    render_data_completeness_report,
)


def test_render_data_completeness_report_classifies_residual_gaps(tmp_path) -> None:
    output = tmp_path / "DATA-COMPLETENESS.md"
    report = CompletenessReport(
        metrics=(
            Metric("members_missing_party", 12, "member stubs"),
            Metric("member_titled_utterance_actionable_mapping_rate_pct", 99.4, "mapping"),
            Metric("safe_utterance_mapping_candidates", 0, "no unsafe auto mapping"),
        ),
        tables=(
            SampleTable(
                title="Missing Party Member Stubs",
                rows=({"name": "추미애", "classification": "referenced_member_stub"},),
            ),
            SampleTable(
                title="Member-titled Utterance Mapping By Title",
                rows=(
                    {
                        "speaker_title": "의장",
                        "total_utterances": 10,
                        "mapped_utterances": 9,
                        "mapping_rate_pct": "90.00",
                    },
                ),
            ),
        ),
        conclusions=(
            "Do not backfill profile party from point-in-time vote party.",
            "No unique member reference exists for unmapped member-titled utterances.",
        ),
    )

    render_data_completeness_report(report, output)

    text = output.read_text()
    assert "# Data Completeness Follow-up" in text
    assert "| `members_missing_party` | 12 | member stubs |" in text
    assert "| `member_titled_utterance_actionable_mapping_rate_pct` | 99.4 | mapping |" in text
    assert "## Missing Party Member Stubs" in text
    assert "## Member-titled Utterance Mapping By Title" in text
    assert "| name | classification |" in text
    assert "- Do not backfill profile party from point-in-time vote party." in text


def test_render_data_completeness_report_handles_empty_tables(tmp_path) -> None:
    output = tmp_path / "DATA-COMPLETENESS.md"
    report = CompletenessReport(
        metrics=(),
        tables=(SampleTable(title="Empty", rows=()),),
        conclusions=(),
    )

    render_data_completeness_report(report, output)

    assert "_No rows._" in output.read_text()
