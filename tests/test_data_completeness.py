"""10% data completeness report behavior."""

from congress_db.ops.data_completeness import (
    CompletenessReport,
    Metric,
    SampleTable,
    generate_data_completeness_report,
    render_data_completeness_report,
)
from congress_db.ops.utterance_mapping_quality import MemberUtteranceMappingQuality


class _Description:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self) -> None:
        self.calls = 0
        self.description: list[_Description] = []
        self._rows: list[tuple[object, ...]] = []
        self._row: tuple[object, ...] | None = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: object | None = None) -> None:
        self.calls += 1
        if self.calls == 1:
            self.description = []
            self._rows = []
        elif self.calls == 2:
            self.description = []
            self._rows = []
        elif self.calls == 3:
            self.description = [
                _Description("bill_metadata_gaps"),
                _Description("bills_missing_propose_dt"),
                _Description("bills_missing_summary"),
                _Description("bills_missing_summary_fillable"),
                _Description("bills_missing_summary_accepted_gap"),
                _Description("vote_created_bill_gaps"),
                _Description("non_vote_bill_gaps"),
            ]
            self._row = (3, 0, 3, 1, 2, 0, 3)
        elif self.calls == 4:
            self.description = [
                _Description("total_utterances"),
                _Description("mapped_utterances"),
            ]
            self._row = (1000, 615)
        else:
            self.description = []
            self._rows = []

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _FakeConn:
    def __init__(self, cur: _FakeCursor) -> None:
        self.cur = cur

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cur


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


def test_generate_data_completeness_report_separates_member_titled_and_overall_mapping(
    monkeypatch, tmp_path
) -> None:
    cur = _FakeCursor()

    def fake_get_conn() -> _FakeConn:
        return _FakeConn(cur)

    def fake_member_mapping(_cur: object) -> MemberUtteranceMappingQuality:
        return MemberUtteranceMappingQuality(
            total_utterances=100,
            mapped_utterances=100,
            unmapped_utterances=0,
            ambiguous_name_unmapped=0,
            safe_mapping_candidate_unmapped=0,
            no_member_reference_unmapped=0,
            mapping_rate_pct=100.0,
            actionable_mapping_rate_pct=100.0,
            by_title=(),
            unmapped_speakers=(),
        )

    monkeypatch.setattr("congress_db.ops.data_completeness.get_conn", fake_get_conn)
    monkeypatch.setattr(
        "congress_db.ops.data_completeness.load_member_utterance_mapping_quality",
        fake_member_mapping,
    )

    report = generate_data_completeness_report(tmp_path / "DATA-COMPLETENESS.md")

    metrics = {metric.name: metric for metric in report.metrics}
    assert metrics["bills_missing_summary"].value == 3
    assert metrics["bills_missing_summary_fillable"].value == 1
    assert metrics["bills_missing_summary_accepted_gap"].value == 2
    assert metrics["member_titled_utterance_mapping_rate_pct"].value == 100.0
    assert metrics["overall_utterance_mapping_rate_pct"].value == 61.5
    assert "BPMBILLSUMMARY" in metrics["bills_missing_summary_fillable"].interpretation
    assert "accepted-gap" in metrics["bills_missing_summary_accepted_gap"].interpretation
    assert "Member-titled only" in metrics["member_titled_utterance_mapping_rate_pct"].interpretation
    assert "All utterances" in metrics["overall_utterance_mapping_rate_pct"].interpretation
