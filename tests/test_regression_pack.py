"""Issue #89 retrieval regression pack behavior."""

from __future__ import annotations

import json
from datetime import date

from congress_db.core.db import get_conn
from congress_db.ops.regression_pack import (
    BoundaryNote,
    CheckResult,
    PromulgationSignal,
    RegressionPackReport,
    ScenarioResult,
    _classify_promulgation_signal,
    _expected_zero_check,
    _floor_check,
    _load_view_checks,
    render_regression_json,
    render_regression_report,
)


def test_floor_checks_are_minimums_not_exact_matches() -> None:
    check = _floor_check(
        metric="passed_bills",
        label="passed bills",
        current=9,
        floor=7,
        detail="minimum anchor",
    )

    assert check.passed is True
    assert check.kind == "floor"
    assert check.current == 9
    assert check.floor == 7


def test_view_checks_pass_when_data_freshness_exposes_domains() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        checks = _load_view_checks(cur)
    assert len(checks) == 1
    assert checks[0].metric == "data_freshness_domains"
    assert checks[0].passed
    assert checks[0].current >= 5


def test_report_fails_when_view_check_fails() -> None:
    failing = CheckResult(
        metric="data_freshness_domains",
        label="data_freshness 뷰 도메인 행 수",
        kind="floor",
        current=0,
        floor=5,
        expected=None,
        passed=False,
        detail="broken view",
    )
    report = RegressionPackReport(generated_at="t", scenarios=(), view_checks=(failing,))
    assert report.passed is False


def test_expected_zero_check_requires_zero() -> None:
    pass_check = _expected_zero_check(
        metric="expected_zero_bill_hits",
        label="채상병 특검",
        current=0,
        detail="alias is skill layer",
    )
    fail_check = _expected_zero_check(
        metric="expected_zero_bill_hits",
        label="채상병 특검",
        current=1,
        detail="alias is skill layer",
    )

    assert pass_check.passed is True
    assert fail_check.passed is False
    assert fail_check.expected == 0


def test_promulgation_classifier_separates_normal_non_law_from_quality_gap() -> None:
    normal = _classify_promulgation_signal(
        {
            "bill_no": "2207635",
            "bill_name": "의대정원 관련 감사요구안",
            "proc_result": "원안가결",
            "promulgation_dt": None,
            "prom_no": None,
            "prom_law_nm": None,
        }
    )
    gap = _classify_promulgation_signal(
        {
            "bill_no": "2206772",
            "bill_name": "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법안",
            "proc_result": "원안가결",
            "promulgation_dt": date(2026, 1, 21),
            "prom_no": "20676",
            "prom_law_nm": None,
        }
    )

    assert normal.status == "normal"
    assert normal.classification == "not_promulgable"
    assert normal.tag == "정상 경계"
    assert gap.status == "quality_gap"
    assert gap.classification == "prom_law_nm_missing"
    assert gap.tag == "[1]"


def test_render_regression_outputs_include_status_thresholds_and_quality_gaps(tmp_path) -> None:
    markdown_path = tmp_path / "REGRESSION-PACK.md"
    json_path = tmp_path / "REGRESSION-PACK.json"
    gap = PromulgationSignal(
        bill_no="2206772",
        bill_name="인공지능 발전과 신뢰 기반 조성 등에 관한 기본법안",
        proc_result="원안가결",
        promulgation_dt="2026-01-21",
        prom_no="20676",
        prom_law_nm=None,
        tag="[1]",
        classification="prom_law_nm_missing",
        status="quality_gap",
        detail="공포된 법안인데 prom_law_nm이 NULL이다.",
    )
    scenario = ScenarioResult(
        key="ai_basic_act",
        title="AI 기본법",
        bill_keyword="인공지능",
        expected_zero_keyword=None,
        checks=(
            CheckResult(
                metric="canonical_keyword_hits",
                label="canonical bill_no reachable by keyword",
                kind="floor",
                current=2,
                floor=2,
                expected=None,
                passed=True,
                detail="floor check",
            ),
        ),
        keyword_counts={"bill_hits": 12},
        bill_metrics={"canonical_keyword_hits": 2},
        canonical_bills=(
            {
                "bill_no": "2206772",
                "bill_name": "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법안",
            },
        ),
        lineage_rows=(),
        promulgation_signals=(gap,),
        quality_gaps=(gap,),
        boundary_notes=(
            BoundaryNote(
                tag="[3]",
                title="법제처 boundary",
                detail="현행법 본문은 out of scope",
            ),
        ),
    )
    report = RegressionPackReport(generated_at="2026-06-11T00:00:00+00:00", scenarios=(scenario,))

    render_regression_report(report, markdown_path)
    render_regression_json(report, json_path)

    markdown = markdown_path.read_text()
    assert "# Retrieval Regression Pack" in markdown
    assert "Overall status: **PASS**" in markdown
    assert "| `canonical_keyword_hits` | 2 | >= 2 | PASS |" in markdown
    assert "prom_law_nm_missing" in markdown
    payload = json.loads(json_path.read_text())
    assert payload["overall_status"] == "PASS"
    assert payload["scenarios"][0]["status"] == "PASS"
    assert payload["scenarios"][0]["quality_gaps"][0]["classification"] == "prom_law_nm_missing"
