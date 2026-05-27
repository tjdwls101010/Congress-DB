"""10% 데이터 완성도 follow-up 리포트."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .db import get_conn

DEFAULT_DATA_COMPLETENESS_REPORT = Path("docs/DATA-COMPLETENESS.md")


@dataclass(frozen=True)
class Metric:
    """데이터 완성도 지표."""

    name: str
    value: int
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


def generate_data_completeness_report(
    output_path: Path = DEFAULT_DATA_COMPLETENESS_REPORT,
) -> CompletenessReport:
    """현재 DB의 데이터 완성도 신호를 분류하고 Markdown으로 저장한다."""
    with get_conn() as conn, conn.cursor() as cur:
        missing_party_rows = _load_missing_party_members(cur)
        bill_gap_rows = _load_bill_metadata_gaps(cur)
        unmapped_speaker_rows = _load_unmapped_member_titled_speakers(cur)
        gap_counts = _load_gap_counts(cur)
        report = CompletenessReport(
            metrics=_build_metrics(missing_party_rows, gap_counts),
            tables=(
                SampleTable("Missing Party Member Stubs", missing_party_rows),
                SampleTable("Vote-created Bill Metadata Gaps", bill_gap_rows),
                SampleTable("Unmapped Member-titled Speakers", unmapped_speaker_rows),
            ),
            conclusions=_build_conclusions(unmapped_speaker_rows),
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
            'vote_created_bill_stub_until_full_bill_load' AS "classification"
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
        ), unmapped AS (
            SELECT speaker_name, COUNT(*) AS utterances
            FROM utterances
            WHERE speaker_title IN ('위원', '의원')
              AND speaker_mona_cd IS NULL
            GROUP BY speaker_name
        ), matches AS (
            SELECT
                u.speaker_name,
                u.utterances,
                COUNT(m.mona_cd) AS member_matches
            FROM unmapped u
            LEFT JOIN members m ON m.hg_nm = u.speaker_name
            GROUP BY u.speaker_name, u.utterances
        )
        SELECT
            (SELECT COUNT(*) FROM bill_gaps) AS bill_metadata_gaps,
            (SELECT COUNT(*) FROM bill_gaps WHERE propose_dt IS NULL) AS bills_missing_propose_dt,
            (SELECT COUNT(*) FROM bill_gaps WHERE summary IS NULL OR summary = '') AS bills_missing_summary,
            (SELECT COUNT(*) FROM bill_gaps WHERE has_votes) AS vote_created_bill_gaps,
            COALESCE((SELECT SUM(utterances)::int FROM matches), 0)
                AS unmapped_member_titled_utterances,
            COALESCE((
                SELECT SUM(utterances)::int FROM matches WHERE member_matches = 1
            ), 0) AS safe_utterance_mapping_candidates
        """
    )
    row = cur.fetchone()
    columns = [description.name for description in cur.description]
    return dict(zip(columns, row, strict=True))


def _load_unmapped_member_titled_speakers(cur: object) -> tuple[dict[str, object], ...]:
    cur.execute(
        """
        WITH unmapped AS (
            SELECT speaker_name, COUNT(*) AS utterances
            FROM utterances
            WHERE speaker_title IN ('위원', '의원')
              AND speaker_mona_cd IS NULL
            GROUP BY speaker_name
        ), matches AS (
            SELECT
                u.speaker_name,
                u.utterances,
                COUNT(m.mona_cd) AS member_matches
            FROM unmapped u
            LEFT JOIN members m ON m.hg_nm = u.speaker_name
            GROUP BY u.speaker_name, u.utterances
        )
        SELECT
            speaker_name AS "speaker_name",
            utterances AS "utterances",
            member_matches AS "member_name_matches",
            CASE
                WHEN member_matches = 0 THEN 'no_member_reference'
                WHEN member_matches = 1 THEN 'safe_mapping_candidate'
                ELSE 'ambiguous_name'
            END AS "classification"
        FROM matches
        ORDER BY utterances DESC, speaker_name
        LIMIT 25
        """
    )
    return _fetch_dicts(cur)


def _build_metrics(
    missing_party_rows: Sequence[Mapping[str, object]],
    gap_counts: Mapping[str, int],
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
            "unmapped_member_titled_utterances",
            gap_counts["unmapped_member_titled_utterances"],
            "Utterances with member-like title but no safe member FK in current members table.",
        ),
        Metric(
            "safe_utterance_mapping_candidates",
            gap_counts["safe_utterance_mapping_candidates"],
            "Rows that can be auto-mapped by unique member name. Current sample should stay zero.",
        ),
    )


def _build_conclusions(
    unmapped_speaker_rows: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    safe_candidates = [
        row for row in unmapped_speaker_rows
        if row["classification"] == "safe_mapping_candidate"
    ]
    mapping_conclusion = (
        "No unique member reference exists for sampled unmapped member-titled utterances, "
        "so the ingest path should not fabricate `speaker_mona_cd` values."
        if not safe_candidates
        else "Some unique member references exist; those should be mapped in the utterance ingest path."
    )
    return (
        "Do not backfill `members.poly_nm` from `votes.poly_nm_at_vote` in this slice; vote party is point-in-time data, while `members.poly_nm` is profile metadata.",
        "Vote-created bill references are expected during 10% calibration because the votes slice can touch bills outside the 10% bill-list slice; full bill load should enrich them.",
        mapping_conclusion,
        "Keep these metrics visible in the sanity report until they are either resolved by full load or explicitly accepted for Supabase migration.",
    )


def _fetch_dicts(cur: object) -> tuple[dict[str, object], ...]:
    columns = [description.name for description in cur.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in cur.fetchall())


def _render_markdown(report: CompletenessReport) -> str:
    lines = [
        "# Data Completeness Follow-up",
        "",
        "This report classifies the data quality signals surfaced by the 10% sanity check.",
        "It separates safe fixes from expected calibration artifacts and unsafe automatic mapping.",
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
