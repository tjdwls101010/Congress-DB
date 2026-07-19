"""Issue #89 retrieval regression pack.

이 모듈은 스킬 소비가 기대하는 4개 anchor 질의를 read-only DB 권한으로 실행해
사람이 읽는 Markdown과 gate용 JSON을 같이 만든다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.db import get_readonly_conn

DEFAULT_REGRESSION_REPORT = Path("docs/ops/REGRESSION-PACK.md")
DEFAULT_REGRESSION_JSON = Path("docs/ops/REGRESSION-PACK.json")
SEARCH_LIMIT = 10_000
PASSED_PROC_RESULTS = ("원안가결", "수정가결")
NON_PROMULGABLE_MARKERS = (
    "감사요구안",
    "수사요구안",
    "결의안",
    "동의안",
    "승인안",
    "규칙안",
)


@dataclass(frozen=True)
class BoundaryNote:
    """회귀 실패가 아니라 정상 경계로 기록해야 하는 한계."""

    tag: str
    title: str
    detail: str


@dataclass(frozen=True)
class RelationAnchor:
    """원안→대안 canonical lineage anchor."""

    source_bill_no: str
    target_bill_no: str
    relation_type: str = "대안반영"


@dataclass(frozen=True)
class ScenarioSpec:
    """4개 anchor 시나리오의 threshold 계약."""

    key: str
    title: str
    bill_keyword: str
    canonical_bill_nos: tuple[str, ...]
    bill_keyword_floor: int
    canonical_keyword_floor: int = 0
    passed_bill_floor: int = 0
    final_outcome_floor: int = 0
    promulgated_floor: int = 0
    not_promulgable_floor: int = 0
    expected_zero_keyword: str | None = None
    relation_anchors: tuple[RelationAnchor, ...] = ()
    scenario_notes: tuple[BoundaryNote, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    """단일 pass/fail gate check."""

    metric: str
    label: str
    kind: str
    current: int
    floor: int | None
    expected: int | None
    passed: bool
    detail: str


@dataclass(frozen=True)
class PromulgationSignal:
    """공포 bridge의 정상/품질갭 분류."""

    bill_no: str
    bill_name: str
    proc_result: str | None
    promulgation_dt: str | None
    prom_no: str | None
    prom_law_nm: str | None
    tag: str
    classification: str
    status: str
    detail: str


@dataclass(frozen=True)
class ScenarioResult:
    """한 anchor 시나리오 실행 결과."""

    key: str
    title: str
    bill_keyword: str
    expected_zero_keyword: str | None
    checks: tuple[CheckResult, ...]
    keyword_counts: Mapping[str, int]
    bill_metrics: Mapping[str, int]
    canonical_bills: Sequence[Mapping[str, object]]
    lineage_rows: Sequence[Mapping[str, object]]
    promulgation_signals: tuple[PromulgationSignal, ...]
    quality_gaps: tuple[PromulgationSignal, ...]
    boundary_notes: tuple[BoundaryNote, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


@dataclass(frozen=True)
class RegressionPackReport:
    """전체 retrieval regression pack 결과."""

    generated_at: str
    scenarios: tuple[ScenarioResult, ...]
    view_checks: tuple[CheckResult, ...] = ()

    @property
    def passed(self) -> bool:
        return all(scenario.passed for scenario in self.scenarios) and all(
            check.passed for check in self.view_checks
        )


_FRESHNESS_DOMAINS = (
    "bills",
    "members",
    "votes",
    "bill_final_outcomes",
    "bill_relations",
)


def _load_view_checks(cur: object) -> tuple[CheckResult, ...]:
    """소비 표면 floor 게이트(WI4·WI4b). 새 마이그레이션 적용 전(대상 객체 부재)에는 통과
    처리해 '적용 전 회귀팩' 베이스라인을 깨지 않고, 적용 후에는 floor를 강제한다."""
    return _data_freshness_check(cur) + _is_law_bill_classification_check(cur)


def _data_freshness_check(cur: object) -> tuple[CheckResult, ...]:
    """data_freshness가 도메인 1행씩 노출하는지(WI4)."""
    cur.execute("SELECT to_regclass('public.data_freshness')")
    exists = cur.fetchone()[0] is not None
    floor = len(_FRESHNESS_DOMAINS)
    if not exists:
        return (
            CheckResult(
                metric="data_freshness_domains",
                label="data_freshness 뷰 도메인 행 수",
                kind="floor",
                current=0,
                floor=floor,
                expected=None,
                passed=True,
                detail="data_freshness 뷰 미적용(마이그레이션 034 적용 전) — 적용 후 도메인 floor를 강제한다.",
            ),
        )
    cur.execute("SELECT count(*) FROM data_freshness")
    domain_count = int(cur.fetchone()[0])
    return (
        CheckResult(
            metric="data_freshness_domains",
            label="data_freshness 뷰 도메인 행 수",
            kind="floor",
            current=domain_count,
            floor=floor,
            expected=None,
            passed=domain_count >= floor,
            detail=f"신선도 뷰가 {floor}개 스테이지(도메인) 1행씩 노출해 소비자가 단정 전 기준일을 확인하게 한다.",
        ),
    )


def _is_law_bill_classification_check(cur: object) -> tuple[CheckResult, ...]:
    """is_law_bill 생성컬럼이 살아 있는지 — 법률안 수 > 비-법률 수 분류 floor(WI4b·C2)."""
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'bills'
              AND column_name = 'is_law_bill'
        )
        """
    )
    exists = bool(cur.fetchone()[0])
    if not exists:
        return (
            CheckResult(
                metric="is_law_bill_majority",
                label="법률안 수 > 비-법률 수",
                kind="floor",
                current=0,
                floor=1,
                expected=None,
                passed=True,
                detail="is_law_bill 생성컬럼 미적용(마이그레이션 037 적용 전) — 적용 후 분류 floor를 강제한다.",
            ),
        )
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE is_law_bill),
               count(*) FILTER (WHERE NOT is_law_bill)
        FROM bills
        """
    )
    law_count, non_law_count = (int(v) for v in cur.fetchone())
    return (
        CheckResult(
            metric="is_law_bill_majority",
            label="법률안 수 > 비-법률 수",
            kind="floor",
            current=law_count,
            floor=non_law_count + 1,
            expected=None,
            passed=law_count > non_law_count,
            detail="is_law_bill이 대다수 의안을 법률안으로 분류해야 정상(정규식이 깨져 전부 비-법률로 뒤집히면 계류 집계가 붕괴).",
        ),
    )


COMMON_BOUNDARY_NOTES = (
    BoundaryNote(
        tag="[3]",
        title="법제처 boundary",
        detail="현행법, 시행령, 판례 본문은 이 DB의 scope 밖이다. "
        "이 DB는 공포 bridge(prom_law_nm/prom_no/promulgation_dt)까지만 제공한다.",
    ),
    BoundaryNote(
        tag="[4]",
        title="skill layer boundary",
        detail="별칭 확장, stance 합성, 여론/WebSearch는 스킬 layer에서 처리한다.",
    ),
)


SCENARIO_SPECS = (
    ScenarioSpec(
        key="jeonse_fraud",
        title="전세사기",
        bill_keyword="전세사기",
        canonical_bill_nos=("2217510", "2218526"),
        bill_keyword_floor=7,
        canonical_keyword_floor=1,
        passed_bill_floor=7,
        final_outcome_floor=7,
        promulgated_floor=1,
        relation_anchors=(RelationAnchor("2217510", "2218526"),),
        scenario_notes=(
            BoundaryNote(
                tag="anchor",
                title="canonical lineage",
                detail="원안 family bill_no 2217510이 대안 bill_no 2218526으로 "
                "해소되고, 2218526은 2026-05-12 공포 anchor다.",
            ),
        ),
    ),
    ScenarioSpec(
        key="medical_school_quota",
        title="의대정원",
        bill_keyword="의대정원",
        canonical_bill_nos=("2207635",),
        bill_keyword_floor=1,
        canonical_keyword_floor=1,
        not_promulgable_floor=1,
        scenario_notes=(
            BoundaryNote(
                tag="정상 경계",
                title="not_promulgable",
                detail="bill_no 2207635는 감사요구안 원안가결이다. 공포가 없는 것은 "
                "정상적인 비-법률 의안 outcome이며 결측 공포 defect가 아니다.",
            ),
        ),
    ),
    ScenarioSpec(
        key="ai_basic_act",
        title="AI 기본법",
        bill_keyword="인공지능",
        canonical_bill_nos=("2206772", "2215126"),
        bill_keyword_floor=2,
        canonical_keyword_floor=2,
        final_outcome_floor=1,
        promulgated_floor=1,
        scenario_notes=(
            BoundaryNote(
                tag="[1]",
                title="known prom_law_nm gap",
                detail="bill_no 2206772는 공포됐지만 prom_law_nm이 NULL인 known "
                "quality gap이다. 현행법 본문 부재 [3]와 구분해 표시한다.",
            ),
        ),
    ),
    ScenarioSpec(
        key="marine_death_special_prosecutor",
        title="채상병 특검",
        bill_keyword="순직 해병",
        canonical_bill_nos=("2212725",),
        bill_keyword_floor=1,
        canonical_keyword_floor=1,
        scenario_notes=(
            BoundaryNote(
                tag="[4]",
                title="alias is the consumer's job",
                detail="구어 '채상병'과 공식 '순직 해병'의 별칭은 [4] 스킬 layer 몫이다. "
                "스킬은 여러 키워드(채상병·순직 해병)로 스스로 검색하므로, DB·regression은 "
                "어휘 변형을 게이트로 모델링하지 않고 canonical `순직 해병` 경로(2212725)만 확인한다.",
            ),
        ),
    ),
)


def run_regression_pack(
    *,
    markdown_path: Path = DEFAULT_REGRESSION_REPORT,
    json_path: Path = DEFAULT_REGRESSION_JSON,
) -> RegressionPackReport:
    """4개 retrieval scenario를 실행하고 Markdown/JSON 리포트를 저장한다."""
    with get_readonly_conn() as conn, conn.cursor() as cur:
        scenarios = tuple(_load_scenario(cur, spec) for spec in SCENARIO_SPECS)
        view_checks = _load_view_checks(cur)

    report = RegressionPackReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        scenarios=scenarios,
        view_checks=view_checks,
    )
    render_regression_report(report, markdown_path)
    render_regression_json(report, json_path)
    return report


def render_regression_report(report: RegressionPackReport, output_path: Path) -> None:
    """사람이 읽는 Markdown regression 리포트를 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(report))


def render_regression_json(report: RegressionPackReport, output_path: Path) -> None:
    """기계가 읽는 pass/fail JSON gate signal을 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_payload(report)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _load_scenario(cur: object, spec: ScenarioSpec) -> ScenarioResult:
    keyword_counts = _load_keyword_counts(cur, spec.bill_keyword)
    expected_zero_counts = (
        _load_keyword_counts(cur, spec.expected_zero_keyword)
        if spec.expected_zero_keyword is not None
        else {"bill_hits": 0}
    )
    bill_metrics = _load_bill_metrics(cur, spec.bill_keyword, spec.canonical_bill_nos)
    canonical_keyword_hits = _count_canonical_keyword_hits(
        cur,
        spec.bill_keyword,
        spec.canonical_bill_nos,
    )
    canonical_bills = _load_canonical_bills(cur, spec.canonical_bill_nos)
    lineage_rows = _load_lineage_rows(
        cur,
        tuple(anchor.source_bill_no for anchor in spec.relation_anchors),
    )
    relation_match_count = _count_relation_matches(lineage_rows, spec.relation_anchors)
    promulgation_signals = tuple(
        _classify_promulgation_signal(row) for row in canonical_bills
    )
    normal_not_promulgable_count = sum(
        1
        for signal in promulgation_signals
        if signal.classification == "not_promulgable"
    )
    checks = _build_checks(
        spec,
        keyword_counts=keyword_counts,
        expected_zero_counts=expected_zero_counts,
        bill_metrics=bill_metrics,
        canonical_keyword_hits=canonical_keyword_hits,
        relation_match_count=relation_match_count,
        normal_not_promulgable_count=normal_not_promulgable_count,
    )
    return ScenarioResult(
        key=spec.key,
        title=spec.title,
        bill_keyword=spec.bill_keyword,
        expected_zero_keyword=spec.expected_zero_keyword,
        checks=checks,
        keyword_counts=keyword_counts,
        bill_metrics={
            **bill_metrics,
            "canonical_keyword_hits": canonical_keyword_hits,
            "relation_anchor_matches": relation_match_count,
            "not_promulgable_normals": normal_not_promulgable_count,
        },
        canonical_bills=canonical_bills,
        lineage_rows=lineage_rows,
        promulgation_signals=promulgation_signals,
        quality_gaps=tuple(
            signal for signal in promulgation_signals if signal.status == "quality_gap"
        ),
        boundary_notes=COMMON_BOUNDARY_NOTES + spec.scenario_notes,
    )


def _build_checks(
    spec: ScenarioSpec,
    *,
    keyword_counts: Mapping[str, int],
    expected_zero_counts: Mapping[str, int],
    bill_metrics: Mapping[str, int],
    canonical_keyword_hits: int,
    relation_match_count: int,
    normal_not_promulgable_count: int,
) -> tuple[CheckResult, ...]:
    checks: list[CheckResult] = [
        _floor_check(
            metric="bill_keyword_hits",
            label=f"`{spec.bill_keyword}` bill retrieval",
            current=keyword_counts["bill_hits"],
            floor=spec.bill_keyword_floor,
            detail="search_bills() hit count; floor is a minimum, not an exact match.",
        ),
        _floor_check(
            metric="canonical_bill_rows",
            label="canonical bill_no rows",
            current=bill_metrics["canonical_bill_count"],
            floor=len(spec.canonical_bill_nos),
            detail="Every scenario anchor bill_no must still exist in bills.",
        ),
    ]

    if spec.canonical_keyword_floor:
        checks.append(
            _floor_check(
                metric="canonical_keyword_hits",
                label="canonical bill_no reachable by keyword",
                current=canonical_keyword_hits,
                floor=spec.canonical_keyword_floor,
                detail=f"search_bills(`{spec.bill_keyword}`) must reach canonical anchors.",
            )
        )
    if spec.passed_bill_floor:
        checks.append(
            _floor_check(
                metric="passed_bills",
                label="passed bills",
                current=bill_metrics["passed_bill_count"],
                floor=spec.passed_bill_floor,
                detail="proc_result in 원안가결/수정가결 within the scenario bill scope.",
            )
        )
    if spec.final_outcome_floor:
        checks.append(
            _floor_check(
                metric="final_outcome_rows",
                label="final outcome rows",
                current=bill_metrics["final_outcome_rows"],
                floor=spec.final_outcome_floor,
                detail="bill_final_outcomes rows joined by bill_no.",
            )
        )
    if spec.promulgated_floor:
        checks.append(
            _floor_check(
                metric="promulgated_rows",
                label="promulgated rows",
                current=bill_metrics["promulgated_rows"],
                floor=spec.promulgated_floor,
                detail="Rows with bill_final_outcomes.promulgation_dt present.",
            )
        )
    if spec.not_promulgable_floor:
        checks.append(
            _floor_check(
                metric="not_promulgable_normals",
                label="normal not-promulgable outcomes",
                current=normal_not_promulgable_count,
                floor=spec.not_promulgable_floor,
                detail="Non-law passed 의안 with no promulgation is a normal boundary.",
            )
        )
    if spec.relation_anchors:
        checks.append(
            _floor_check(
                metric="relation_anchor_matches",
                label="canonical lineage anchors",
                current=relation_match_count,
                floor=len(spec.relation_anchors),
                detail="bill_relations + bill_source_aliases resolves source→target bill_no.",
            )
        )
    if spec.expected_zero_keyword is not None:
        checks.append(
            _expected_zero_check(
                metric="expected_zero_bill_hits",
                label=f"`{spec.expected_zero_keyword}` bill retrieval",
                current=expected_zero_counts["bill_hits"],
                detail="0 is expected here; alias expansion is [4] skill-layer scope.",
            )
        )
    return tuple(checks)


def _floor_check(
    *,
    metric: str,
    label: str,
    current: int,
    floor: int,
    detail: str,
) -> CheckResult:
    return CheckResult(
        metric=metric,
        label=label,
        kind="floor",
        current=current,
        floor=floor,
        expected=None,
        passed=current >= floor,
        detail=detail,
    )


def _expected_zero_check(
    *,
    metric: str,
    label: str,
    current: int,
    detail: str,
) -> CheckResult:
    return CheckResult(
        metric=metric,
        label=label,
        kind="expected_zero",
        current=current,
        floor=None,
        expected=0,
        passed=current == 0,
        detail=detail,
    )


def _load_keyword_counts(cur: object, bill_keyword: str) -> dict[str, int]:
    cur.execute(
        """
        SELECT
            (SELECT COUNT(*)::int FROM search_bills(%s, %s)) AS bill_hits
        """,
        (bill_keyword, SEARCH_LIMIT),
    )
    row = cur.fetchone()
    return {"bill_hits": int(row[0])}


def _load_bill_metrics(
    cur: object,
    keyword: str,
    canonical_bill_nos: Sequence[str],
) -> dict[str, int]:
    cur.execute(
        """
        WITH keyword_hits AS (
            SELECT bill_id
            FROM search_bills(%s, %s)
        ), scenario_bills AS (
            SELECT DISTINCT
                b.bill_id,
                b.bill_no,
                b.proc_result
            FROM bills b
            LEFT JOIN keyword_hits kh ON kh.bill_id = b.bill_id
            WHERE kh.bill_id IS NOT NULL
               OR b.bill_no = ANY(%s)
        )
        SELECT
            COUNT(*)::int AS bill_scope_count,
            COUNT(*) FILTER (WHERE b.bill_no = ANY(%s))::int AS canonical_bill_count,
            COUNT(*) FILTER (WHERE proc_result = ANY(%s))::int AS passed_bill_count,
            COUNT(o.bill_no)::int AS final_outcome_rows,
            COUNT(o.bill_no) FILTER (WHERE o.promulgation_dt IS NOT NULL)::int
                AS promulgated_rows,
            COUNT(o.bill_no) FILTER (
                WHERE o.promulgation_dt IS NOT NULL
                  AND (o.prom_law_nm IS NULL OR btrim(o.prom_law_nm) = '')
            )::int AS prom_law_nm_gap_rows
        FROM scenario_bills b
        LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
        """,
        (
            keyword,
            SEARCH_LIMIT,
            list(canonical_bill_nos),
            list(canonical_bill_nos),
            list(PASSED_PROC_RESULTS),
        ),
    )
    row = cur.fetchone()
    columns = [description.name for description in cur.description]
    return {column: int(value or 0) for column, value in zip(columns, row, strict=True)}


def _count_canonical_keyword_hits(
    cur: object,
    keyword: str,
    canonical_bill_nos: Sequence[str],
) -> int:
    if not canonical_bill_nos:
        return 0
    cur.execute(
        """
        SELECT COUNT(DISTINCT bill_no)::int
        FROM search_bills(%s, %s)
        WHERE bill_no = ANY(%s)
        """,
        (keyword, SEARCH_LIMIT, list(canonical_bill_nos)),
    )
    return int(cur.fetchone()[0])


def _load_canonical_bills(
    cur: object,
    canonical_bill_nos: Sequence[str],
) -> tuple[dict[str, object], ...]:
    if not canonical_bill_nos:
        return ()
    cur.execute(
        """
        SELECT
            b.bill_no,
            left(b.bill_name, 140) AS bill_name,
            b.proc_result,
            b.propose_dt,
            o.plenary_dt,
            o.govt_transfer_dt,
            o.promulgation_dt,
            o.prom_no,
            o.prom_law_nm
        FROM bills b
        LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
        WHERE b.bill_no = ANY(%s)
        ORDER BY b.bill_no
        """,
        (list(canonical_bill_nos),),
    )
    return _fetch_dicts(cur)


def _load_lineage_rows(
    cur: object,
    source_bill_nos: Sequence[str],
) -> tuple[dict[str, object], ...]:
    if not source_bill_nos:
        return ()
    # bill_lineage 뷰가 direct+alias 해소를 캡슐화 (raw bill_relations/bill_source_aliases는
    # congress_ro에서 REVOKE됨, #125). 법안명은 소비자 가시 테이블 bills join으로 가져온다.
    cur.execute(
        """
        SELECT
            bl.absorbed_bill_no AS source_bill_no,
            left(sb.bill_name, 110) AS source_bill_name,
            bl.relation_type,
            bl.alternative_bill_id,
            bl.alternative_bill_no AS target_bill_no,
            left(tb.bill_name, 110) AS target_bill_name,
            CASE WHEN bl.alternative_bill_id IS NULL THEN 'unresolved' ELSE 'resolved' END
                AS resolution_path
        FROM bill_lineage bl
        JOIN bills sb ON sb.bill_id = bl.absorbed_bill_id
        LEFT JOIN bills tb ON tb.bill_id = bl.alternative_bill_id
        WHERE bl.absorbed_bill_no = ANY(%s)
        ORDER BY bl.absorbed_bill_no, bl.relation_type, target_bill_no
        """,
        (list(source_bill_nos),),
    )
    return _fetch_dicts(cur)


def _count_relation_matches(
    lineage_rows: Sequence[Mapping[str, object]],
    anchors: Sequence[RelationAnchor],
) -> int:
    count = 0
    for anchor in anchors:
        if any(
            row.get("source_bill_no") == anchor.source_bill_no
            and row.get("target_bill_no") == anchor.target_bill_no
            and row.get("relation_type") == anchor.relation_type
            for row in lineage_rows
        ):
            count += 1
    return count


def _classify_promulgation_signal(row: Mapping[str, object]) -> PromulgationSignal:
    bill_no = str(row.get("bill_no", ""))
    bill_name = str(row.get("bill_name", ""))
    proc_result = _none_or_str(row.get("proc_result"))
    promulgation_dt = _date_or_none(row.get("promulgation_dt"))
    prom_law_nm = _blank_to_none(row.get("prom_law_nm"))
    prom_no = _blank_to_none(row.get("prom_no"))

    if promulgation_dt is not None and prom_law_nm is None:
        return PromulgationSignal(
            bill_no=bill_no,
            bill_name=bill_name,
            proc_result=proc_result,
            promulgation_dt=promulgation_dt,
            prom_no=prom_no,
            prom_law_nm=None,
            tag="[1]",
            classification="prom_law_nm_missing",
            status="quality_gap",
            detail="공포된 법안인데 prom_law_nm이 NULL이다.",
        )
    if promulgation_dt is None and _is_not_promulgable(bill_name):
        return PromulgationSignal(
            bill_no=bill_no,
            bill_name=bill_name,
            proc_result=proc_result,
            promulgation_dt=None,
            prom_no=prom_no,
            prom_law_nm=prom_law_nm,
            tag="정상 경계",
            classification="not_promulgable",
            status="normal",
            detail="비-법률 의안이라 공포 없음이 정상 outcome이다.",
        )
    if promulgation_dt is None and proc_result in PASSED_PROC_RESULTS:
        return PromulgationSignal(
            bill_no=bill_no,
            bill_name=bill_name,
            proc_result=proc_result,
            promulgation_dt=None,
            prom_no=prom_no,
            prom_law_nm=prom_law_nm,
            tag="[1]",
            classification="promulgation_missing_candidate",
            status="quality_gap",
            detail="가결 법안인데 공포 bridge가 비어 있다. 법률안이면 DB 품질 gap이다.",
        )
    return PromulgationSignal(
        bill_no=bill_no,
        bill_name=bill_name,
        proc_result=proc_result,
        promulgation_dt=promulgation_dt,
        prom_no=prom_no,
        prom_law_nm=prom_law_nm,
        tag="ok",
        classification="promulgation_recorded" if promulgation_dt else "not_passed_or_pending",
        status="normal",
        detail="공포 bridge 분류상 추가 gap이 없다.",
    )


def _is_not_promulgable(bill_name: str) -> bool:
    return any(marker in bill_name for marker in NON_PROMULGABLE_MARKERS)


def _fetch_dicts(cur: object) -> tuple[dict[str, object], ...]:
    columns = [description.name for description in cur.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in cur.fetchall())


def _render_markdown(report: RegressionPackReport) -> str:
    lines = [
        "# Retrieval Regression Pack",
        "",
        f"- Generated at: `{report.generated_at}`",
        f"- Overall status: **{'PASS' if report.passed else 'FAIL'}**",
        "- Gate: GitHub issue #89 / M3 demand-gate",
        "- Connection: `CONGRESS_RO_URL` read-only role",
        "",
        "Thresholds are floors unless marked expected-zero. Counts may grow as incremental sync adds rows.",
        "",
        "## Scenario Summary",
        "",
        "| Scenario | Status | Checks | [1] Quality gaps |",
        "| --- | --- | ---: | ---: |",
    ]
    for scenario in report.scenarios:
        lines.append(
            f"| {scenario.title} | {'PASS' if scenario.passed else 'FAIL'} | "
            f"{sum(1 for check in scenario.checks if check.passed)}/{len(scenario.checks)} | "
            f"{len(scenario.quality_gaps)} |"
        )

    for scenario in report.scenarios:
        lines.extend(
            [
                "",
                f"## {scenario.title}",
                "",
                f"- Status: **{'PASS' if scenario.passed else 'FAIL'}**",
                f"- Bill keyword: `{scenario.bill_keyword}`",
            ]
        )
        if scenario.expected_zero_keyword is not None:
            lines.append(f"- Expected-zero keyword: `{scenario.expected_zero_keyword}`")
        lines.extend(
            [
                "",
                "### Gate Checks",
                "",
                "| Metric | Current | Threshold | Status | Detail |",
                "| --- | ---: | --- | --- | --- |",
            ]
        )
        for check in scenario.checks:
            threshold = (
                f">= {check.floor}"
                if check.kind == "floor"
                else f"== {check.expected}"
            )
            lines.append(
                f"| `{check.metric}` | {check.current} | {threshold} | "
                f"{'PASS' if check.passed else 'FAIL'} | {_escape_cell(check.detail)} |"
            )

        lines.extend(["", "### Keyword Counts", ""])
        lines.extend(_render_table((scenario.keyword_counts,)))

        lines.extend(["", "### Canonical Bills", ""])
        lines.extend(_render_table(scenario.canonical_bills))

        lines.extend(["", "### Promulgation Classification", ""])
        lines.extend(
            _render_table(tuple(asdict(signal) for signal in scenario.promulgation_signals))
        )

        lines.extend(["", "### [1] Quality Gaps", ""])
        if scenario.quality_gaps:
            lines.extend(_render_table(tuple(asdict(signal) for signal in scenario.quality_gaps)))
        else:
            lines.append("_No [1] quality gap flagged for this scenario._")

        lines.extend(["", "### Expected Limits", ""])
        lines.extend(_render_table(tuple(asdict(note) for note in scenario.boundary_notes)))

        if scenario.lineage_rows:
            lines.extend(["", "### Canonical Lineage", ""])
            lines.extend(_render_table(scenario.lineage_rows))

    return "\n".join(lines) + "\n"


def _render_table(rows: Sequence[Mapping[str, object]]) -> list[str]:
    if not rows:
        return ["_No rows._"]

    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(_escape_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_escape_cell(_format_value(row.get(header, ""))) for header in headers)
            + " |"
        )
    return lines


def _json_payload(report: RegressionPackReport) -> dict[str, object]:
    payload = _jsonable(asdict(report))
    assert isinstance(payload, dict)
    payload["overall_status"] = "PASS" if report.passed else "FAIL"
    scenarios = payload.get("scenarios", [])
    if isinstance(scenarios, list):
        for scenario_payload, scenario in zip(scenarios, report.scenarios, strict=True):
            if isinstance(scenario_payload, dict):
                scenario_payload["status"] = "PASS" if scenario.passed else "FAIL"
    return payload


def _jsonable(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _escape_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = " ".join(text.split())
    if len(text) > 240:
        text = text[:237].rstrip() + "..."
    return text.replace("|", "\\|")


def _format_value(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return "" if value is None else str(value)


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _none_or_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _date_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value).strip()
    return text or None
