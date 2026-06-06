"""데이터 완성도 follow-up 리포트."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..core.db import get_conn
from .utterance_mapping_quality import (
    MemberUtteranceMappingQuality,
    load_member_utterance_mapping_quality,
)

DEFAULT_DATA_COMPLETENESS_REPORT = Path("docs/ops/DATA-COMPLETENESS.md")


@dataclass(frozen=True)
class Metric:
    """데이터 완성도 지표."""

    name: str
    value: int | float | str
    interpretation: str


@dataclass(frozen=True)
class SampleTable:
    """데이터 완성도 샘플 표."""

    title: str
    rows: Sequence[Mapping[str, object]]


@dataclass(frozen=True)
class CompletenessReport:
    """데이터 완성도 리포트 입력값."""

    metrics: Sequence[Metric]
    tables: Sequence[SampleTable]
    conclusions: Sequence[str]


@dataclass(frozen=True)
class OverallUtteranceMappingQuality:
    """전체 발언 기준 의원 FK 매핑률."""

    total_utterances: int
    mapped_utterances: int
    mapping_rate_pct: float | None


def generate_data_completeness_report(
    output_path: Path = DEFAULT_DATA_COMPLETENESS_REPORT,
) -> CompletenessReport:
    """현재 DB의 데이터 완성도 신호를 분류하고 Markdown으로 저장한다."""
    with get_conn() as conn, conn.cursor() as cur:
        missing_party_rows = _load_missing_party_members(cur)
        bill_gap_rows = _load_bill_metadata_gaps(cur)
        member_mapping = load_member_utterance_mapping_quality(cur)
        unmapped_speaker_rows = tuple(
            row.as_report_row() for row in member_mapping.unmapped_speakers
        )
        mapping_by_title_rows = tuple(row.as_report_row() for row in member_mapping.by_title)
        gap_counts = _load_gap_counts(cur)
        overall_mapping = _load_overall_utterance_mapping(cur)
        report = CompletenessReport(
            metrics=_build_metrics(
                missing_party_rows,
                gap_counts,
                member_mapping,
                overall_mapping,
            ),
            tables=(
                SampleTable("Missing Party Member Stubs", missing_party_rows),
                SampleTable("Bill Metadata Gaps", bill_gap_rows),
                SampleTable("Member-titled Utterance Mapping By Title", mapping_by_title_rows),
                SampleTable("Unmapped Member-titled Speakers", unmapped_speaker_rows),
            ),
            conclusions=_build_conclusions(member_mapping, gap_counts),
        )
    render_data_completeness_report(report, output_path)
    return report


def render_data_completeness_report(report: CompletenessReport, output_path: Path) -> None:
    """데이터 완성도 리포트를 Markdown으로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(report))


def _load_missing_party_members(cur: object) -> tuple[dict[str, object], ...]:
    cur.execute(
        """
        WITH missing AS (
            SELECT mona_cd, hg_nm
            FROM members
            WHERE poly_nm IS NULL OR poly_nm = ''
        ), utterance_counts AS (
            SELECT speaker_mona_cd AS mona_cd, COUNT(*) AS utterances
            FROM utterances
            WHERE speaker_mona_cd IS NOT NULL
            GROUP BY speaker_mona_cd
        ), vote_counts AS (
            SELECT mona_cd, COUNT(*) AS votes
            FROM votes
            GROUP BY mona_cd
        ), lead_counts AS (
            SELECT mona_cd, COUNT(*) AS lead_bills
            FROM bill_lead_proposers
            GROUP BY mona_cd
        ), co_counts AS (
            SELECT mona_cd, COUNT(*) AS co_bills
            FROM bill_coproposers
            GROUP BY mona_cd
        )
        SELECT
            m.hg_nm AS "name",
            m.mona_cd AS "mona_cd",
            latest_vote.poly_nm_at_vote AS "latest_vote_party",
            COALESCE(u.utterances, 0) AS "utterances",
            COALESCE(v.votes, 0) AS "votes",
            COALESCE(l.lead_bills, 0) AS "lead_bills",
            COALESCE(c.co_bills, 0) AS "co_bills",
            'referenced_member_stub' AS "classification"
        FROM missing m
        LEFT JOIN utterance_counts u ON u.mona_cd = m.mona_cd
        LEFT JOIN vote_counts v ON v.mona_cd = m.mona_cd
        LEFT JOIN lead_counts l ON l.mona_cd = m.mona_cd
        LEFT JOIN co_counts c ON c.mona_cd = m.mona_cd
        LEFT JOIN LATERAL (
            SELECT poly_nm_at_vote
            FROM votes
            WHERE votes.mona_cd = m.mona_cd
            ORDER BY vote_date DESC
            LIMIT 1
        ) latest_vote ON true
        ORDER BY COALESCE(u.utterances, 0) DESC, COALESCE(v.votes, 0) DESC, m.hg_nm
        """
    )
    return _fetch_dicts(cur)


def _load_bill_metadata_gaps(cur: object) -> tuple[dict[str, object], ...]:
    cur.execute(
        """
        SELECT
            b.bill_no AS "bill_no",
            left(b.bill_name, 100) AS "bill_name",
            CASE WHEN v.bill_id IS NULL THEN 'false' ELSE 'true' END AS "has_votes",
            concat_ws(
                ', ',
                CASE WHEN b.propose_dt IS NULL THEN 'propose_dt' END,
                CASE WHEN b.summary IS NULL OR b.summary = '' THEN 'summary' END
            ) AS "missing_fields",
            CASE
                WHEN v.bill_id IS NOT NULL THEN 'vote_created_source_metadata_gap_after_full_backfill'
                ELSE 'source_summary_gap_after_full_backfill'
            END AS "classification"
        FROM bills b
        LEFT JOIN (SELECT DISTINCT bill_id FROM votes) v USING (bill_id)
        WHERE b.propose_dt IS NULL
           OR b.summary IS NULL
           OR b.summary = ''
        ORDER BY (v.bill_id IS NOT NULL) DESC, b.bill_no DESC
        LIMIT 20
        """
    )
    return _fetch_dicts(cur)


def _load_gap_counts(cur: object) -> dict[str, int]:
    cur.execute(
        """
        WITH bill_gaps AS (
            SELECT b.bill_id, b.propose_dt, b.summary, v.bill_id IS NOT NULL AS has_votes
            FROM bills b
            LEFT JOIN (SELECT DISTINCT bill_id FROM votes) v USING (bill_id)
            WHERE b.propose_dt IS NULL
               OR b.summary IS NULL
               OR b.summary = ''
        )
        SELECT
            (SELECT COUNT(*) FROM bill_gaps) AS bill_metadata_gaps,
            (SELECT COUNT(*) FROM bill_gaps WHERE propose_dt IS NULL) AS bills_missing_propose_dt,
            (SELECT COUNT(*) FROM bill_gaps WHERE summary IS NULL OR summary = '') AS bills_missing_summary,
            (SELECT COUNT(*) FROM bill_gaps WHERE has_votes) AS vote_created_bill_gaps,
            (SELECT COUNT(*) FROM bill_gaps WHERE NOT has_votes) AS non_vote_bill_gaps
        """
    )
    row = cur.fetchone()
    columns = [description.name for description in cur.description]
    return dict(zip(columns, row, strict=True))


def _load_overall_utterance_mapping(cur: object) -> OverallUtteranceMappingQuality:
    cur.execute(
        """
        SELECT
            COUNT(*)::int AS total_utterances,
            COUNT(*) FILTER (WHERE speaker_mona_cd IS NOT NULL)::int AS mapped_utterances
        FROM utterances
        """
    )
    row = cur.fetchone()
    if not row:
        return OverallUtteranceMappingQuality(
            total_utterances=0,
            mapped_utterances=0,
            mapping_rate_pct=None,
        )
    total = int(row[0])
    mapped = int(row[1])
    return OverallUtteranceMappingQuality(
        total_utterances=total,
        mapped_utterances=mapped,
        mapping_rate_pct=_rate_pct(mapped, total),
    )


def _build_metrics(
    missing_party_rows: Sequence[Mapping[str, object]],
    gap_counts: Mapping[str, int],
    member_mapping: MemberUtteranceMappingQuality,
    overall_mapping: OverallUtteranceMappingQuality,
) -> tuple[Metric, ...]:
    missing_party_count = len(missing_party_rows)
    vote_party_available = sum(1 for row in missing_party_rows if row["latest_vote_party"])
    return (
        Metric(
            "members_missing_party",
            missing_party_count,
            "Referenced member stubs preserved by FK policy; profile metadata is absent.",
        ),
        Metric(
            "member_stubs_with_vote_party",
            vote_party_available,
            "Point-in-time vote party exists, but it is not the same as profile party.",
        ),
        Metric(
            "bill_metadata_gaps",
            gap_counts["bill_metadata_gaps"],
            "Bills missing proposed date or summary.",
        ),
        Metric(
            "vote_created_bill_metadata_gaps",
            gap_counts["vote_created_bill_gaps"],
            "Metadata gaps attached to bills already touched by votes ingest.",
        ),
        Metric(
            "bills_missing_summary",
            gap_counts["bills_missing_summary"],
            "Bills whose summary cannot yet participate in keyword search.",
        ),
        Metric(
            "overall_utterances_total",
            overall_mapping.total_utterances,
            "All utterances in the corpus, including ministers, witnesses, staff, and other non-member speakers.",
        ),
        Metric(
            "overall_mapped_utterances",
            overall_mapping.mapped_utterances,
            "All utterances with `speaker_mona_cd`; this is the whole-corpus member FK count.",
        ),
        Metric(
            "overall_utterance_mapping_rate_pct",
            _metric_rate(overall_mapping.mapping_rate_pct),
            "All utterances mapping rate; this is not expected to be 100% because non-member speakers intentionally have no member FK.",
        ),
        Metric(
            "member_titled_utterances_total",
            member_mapping.total_utterances,
            "Member-titled only: utterances whose speaker_title is one of the 10 member-like titles used by ingest mapping.",
        ),
        Metric(
            "unmapped_member_titled_utterances",
            member_mapping.unmapped_utterances,
            "Member-titled only: utterances with no member FK across the full ingest title set.",
        ),
        Metric(
            "member_titled_utterance_mapping_rate_pct",
            _metric_rate(member_mapping.mapping_rate_pct),
            "Member-titled only: raw mapping rate across the titles that should normally map to legislators.",
        ),
        Metric(
            "ambiguous_name_unmapped_utterances",
            member_mapping.ambiguous_name_unmapped,
            "Unmapped rows intentionally left without FK because the normalized member name is ambiguous.",
        ),
        Metric(
            "member_titled_utterance_actionable_mapping_rate_pct",
            _metric_rate(member_mapping.actionable_mapping_rate_pct),
            "Member-titled only: mapping rate excluding intentionally ambiguous member-name collisions from the denominator.",
        ),
        Metric(
            "safe_utterance_mapping_candidates",
            member_mapping.safe_mapping_candidate_unmapped,
            "Rows that can be auto-mapped by unique normalized member name. Current sample should stay zero.",
        ),
    )


def _build_conclusions(
    member_mapping: MemberUtteranceMappingQuality,
    gap_counts: Mapping[str, int],
) -> tuple[str, ...]:
    mapping_conclusion = (
        "No unique member reference exists for sampled unmapped member-titled utterances, "
        "so the ingest path should not fabricate `speaker_mona_cd` values."
        if member_mapping.safe_mapping_candidate_unmapped == 0
        else "Some unique member references exist; those should be mapped in the utterance ingest path."
    )
    return (
        "Do not backfill `members.poly_nm` from `votes.poly_nm_at_vote` in this slice; vote party is point-in-time data, while `members.poly_nm` is profile metadata.",
        f"{gap_counts['vote_created_bill_gaps']} vote-created bill rows still lack source proposal date and summary after full backfill; keep them as accepted source metadata gaps for migration unless a new source endpoint is added.",
        f"{gap_counts['non_vote_bill_gaps']} non-vote bill rows still lack source summary after full backfill; they affect summary-search recall, not relational integrity.",
        f"Member-titled utterance mapping is {_metric_rate(member_mapping.actionable_mapping_rate_pct)}% after excluding {member_mapping.ambiguous_name_unmapped} ambiguous-name rows from the denominator.",
        mapping_conclusion,
        "Keep these metrics visible through hosted Postgres migration so accepted source gaps do not get mistaken for ingest failures.",
    )


def _metric_rate(value: float | None) -> float | str:
    if value is None:
        return "n/a"
    return value


def _rate_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _fetch_dicts(cur: object) -> tuple[dict[str, object], ...]:
    columns = [description.name for description in cur.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in cur.fetchall())


def _render_markdown(report: CompletenessReport) -> str:
    lines = [
        "# Data Completeness Follow-up",
        "",
        "This report classifies the data quality signals surfaced by the current local backfill.",
        "It separates source metadata gaps, safe fixes, and unsafe automatic mapping.",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Interpretation |",
        "| --- | ---: | --- |",
    ]
    for metric in report.metrics:
        lines.append(
            f"| `{metric.name}` | {metric.value} | {_escape_cell(metric.interpretation)} |"
        )

    lines.extend(["", "## Conclusions", ""])
    for conclusion in report.conclusions:
        lines.append(f"- {conclusion}")

    for table in report.tables:
        lines.extend(["", f"## {table.title}", ""])
        lines.extend(_render_table(table.rows))

    lines.append("")
    return "\n".join(lines)


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
            + " | ".join(_escape_cell(row.get(header, "")) for header in headers)
            + " |"
        )
    return lines


def _escape_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = " ".join(text.split())
    if len(text) > 220:
        text = text[:217].rstrip() + "..."
    return text.replace("|", "\\|")
