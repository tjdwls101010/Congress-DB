"""10% data completeness report behavior."""

from congress_db.ops.data_completeness import (
    CompletenessReport,
    Metric,
    SampleTable,
    generate_data_completeness_report,
    render_data_completeness_report,
)


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
            # _load_missing_party_members
            self.description = []
            self._rows = []
        elif self.calls == 2:
            # _load_bill_metadata_gaps
            self.description = []
            self._rows = []
        elif self.calls == 3:
            # _load_gap_counts
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
            Metric("bills_missing_summary", 3, "summary search recall"),
        ),
        tables=(
            SampleTable(
                title="Missing Party Member Stubs",
                rows=({"name": "추미애", "classification": "referenced_member_stub"},),
            ),
            SampleTable(
                title="Bill Metadata Gaps",
                rows=(
                    {
                        "bill_no": "2299999",
                        "missing_fields": "summary",
                    },
                ),
            ),
        ),
        conclusions=(
            "Do not backfill profile party from point-in-time vote party.",
            "Keep accepted source gaps visible through migration.",
        ),
    )

    render_data_completeness_report(report, output)

    text = output.read_text()
    assert "# Data Completeness Follow-up" in text
    assert "| `members_missing_party` | 12 | member stubs |" in text
    assert "| `bills_missing_summary` | 3 | summary search recall |" in text
    assert "## Missing Party Member Stubs" in text
    assert "## Bill Metadata Gaps" in text
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


def test_generate_data_completeness_report_classifies_bill_summary_gaps(
    monkeypatch, tmp_path
) -> None:
    cur = _FakeCursor()

    def fake_get_conn() -> _FakeConn:
        return _FakeConn(cur)

    monkeypatch.setattr("congress_db.ops.data_completeness.get_conn", fake_get_conn)

    report = generate_data_completeness_report(tmp_path / "DATA-COMPLETENESS.md")

    metrics = {metric.name: metric for metric in report.metrics}
    assert metrics["bills_missing_summary"].value == 3
    assert metrics["bills_missing_summary_fillable"].value == 1
    assert metrics["bills_missing_summary_accepted_gap"].value == 2
    assert "BPMBILLSUMMARY" in metrics["bills_missing_summary_fillable"].interpretation
    assert "accepted-gap" in metrics["bills_missing_summary_accepted_gap"].interpretation
