"""session_groups 캘리브레이션 검증 리포트."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .db import get_conn

DEFAULT_SESSION_GROUPS_REPORT = Path("docs/SESSION-GROUPS-CALIBRATION.md")


@dataclass(frozen=True)
class SessionGroupTypeMetric:
    """회의 유형별 session_group 생성 지표."""

    meeting_type: str
    meetings: int
    skipped: int
    applicable: int
    applicable_with_groups: int
    groups: int
    applicable_success_pct: Decimal | None


@dataclass(frozen=True)
class SessionGroupValidationResult:
    """session_group 정합성 검증 결과."""

    total_meetings: int
    skipped_meetings: int
    applicable_meetings: int
    meetings_with_groups: int
    group_count: int
    utterance_link_count: int
    skipped_with_groups: int
    questioner_fk_missing: int
    utterance_count_mismatch: int
    total_chars_mismatch: int
    respondents_format_invalid: int
    respondent_empty_groups: int
    groups_with_50_plus_utterances: int
    groups_with_100_plus_utterances: int
    max_group_utterance_count: int
    type_metrics: tuple[SessionGroupTypeMetric, ...]


def validate_session_groups(
    output_path: Path = DEFAULT_SESSION_GROUPS_REPORT,
) -> SessionGroupValidationResult:
    """현재 DB의 session_group 생성률과 정합성을 Markdown으로 남긴다."""
    with get_conn() as conn, conn.cursor() as cur:
        result = _load_validation_result(cur)
    render_session_group_report(result, output_path)
    return result


def render_session_group_report(
    result: SessionGroupValidationResult,
    output_path: Path,
) -> None:
    """검증 결과를 Markdown으로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(result))


def _load_validation_result(cur: object) -> SessionGroupValidationResult:
    type_metrics = _load_type_metrics(cur)
    summary = _load_summary(cur)
    integrity = _load_integrity(cur)
    return SessionGroupValidationResult(
        total_meetings=summary["total_meetings"],
        skipped_meetings=summary["skipped_meetings"],
        applicable_meetings=summary["applicable_meetings"],
        meetings_with_groups=summary["meetings_with_groups"],
        group_count=summary["group_count"],
        utterance_link_count=summary["utterance_link_count"],
        skipped_with_groups=integrity["skipped_with_groups"],
        questioner_fk_missing=integrity["questioner_fk_missing"],
        utterance_count_mismatch=integrity["utterance_count_mismatch"],
        total_chars_mismatch=integrity["total_chars_mismatch"],
        respondents_format_invalid=integrity["respondents_format_invalid"],
        respondent_empty_groups=integrity["respondent_empty_groups"],
        groups_with_50_plus_utterances=integrity["groups_with_50_plus_utterances"],
        groups_with_100_plus_utterances=integrity["groups_with_100_plus_utterances"],
        max_group_utterance_count=integrity["max_group_utterance_count"],
        type_metrics=tuple(type_metrics),
    )


def _load_type_metrics(cur: object) -> list[SessionGroupTypeMetric]:
    cur.execute(
        """
        WITH utterance_meetings AS (
            SELECT DISTINCT meeting_id FROM utterances
        ), group_counts AS (
            SELECT meeting_id, COUNT(*) AS group_count
            FROM session_groups
            GROUP BY meeting_id
        ), base AS (
            SELECT
                m.mnts_id,
                m.meeting_type,
                COALESCE(gc.group_count, 0) AS group_count,
                CASE
                    WHEN m.meeting_type IN ('본회의', '소위원회')
                      OR m.title ~ '(소위원회|조세소위|법안심사.*소위|예산결산.*소위|안건조정위원회)'
                    THEN true ELSE false
                END AS skipped
            FROM meetings m
            JOIN utterance_meetings um ON um.meeting_id = m.mnts_id
            LEFT JOIN group_counts gc ON gc.meeting_id = m.mnts_id
        )
        SELECT
            meeting_type,
            COUNT(*) AS meetings,
            COUNT(*) FILTER (WHERE skipped) AS skipped,
            COUNT(*) FILTER (WHERE NOT skipped) AS applicable,
            COUNT(*) FILTER (WHERE NOT skipped AND group_count > 0) AS applicable_with_groups,
            COALESCE(SUM(group_count), 0) AS groups,
            ROUND(
                (COUNT(*) FILTER (WHERE NOT skipped AND group_count > 0))::numeric
                / NULLIF(COUNT(*) FILTER (WHERE NOT skipped), 0) * 100,
                1
            ) AS applicable_success_pct
        FROM base
        GROUP BY meeting_type
        ORDER BY meeting_type
        """
    )
    return [
        SessionGroupTypeMetric(
            meeting_type=row[0],
            meetings=row[1],
            skipped=row[2],
            applicable=row[3],
            applicable_with_groups=row[4],
            groups=row[5],
            applicable_success_pct=row[6],
        )
        for row in cur.fetchall()
    ]


def _load_summary(cur: object) -> dict[str, int]:
    cur.execute(
        """
        WITH utterance_meetings AS (
            SELECT DISTINCT meeting_id FROM utterances
        ), group_counts AS (
            SELECT meeting_id, COUNT(*) AS group_count
            FROM session_groups
            GROUP BY meeting_id
        ), base AS (
            SELECT
                m.mnts_id,
                COALESCE(gc.group_count, 0) AS group_count,
                CASE
                    WHEN m.meeting_type IN ('본회의', '소위원회')
                      OR m.title ~ '(소위원회|조세소위|법안심사.*소위|예산결산.*소위|안건조정위원회)'
                    THEN true ELSE false
                END AS skipped
            FROM meetings m
            JOIN utterance_meetings um ON um.meeting_id = m.mnts_id
            LEFT JOIN group_counts gc ON gc.meeting_id = m.mnts_id
        )
        SELECT
            COUNT(*) AS total_meetings,
            COUNT(*) FILTER (WHERE skipped) AS skipped_meetings,
            COUNT(*) FILTER (WHERE NOT skipped) AS applicable_meetings,
            COUNT(*) FILTER (WHERE group_count > 0) AS meetings_with_groups,
            COALESCE(SUM(group_count), 0) AS group_count,
            (SELECT COUNT(*) FROM utterances WHERE session_group_id IS NOT NULL)
                AS utterance_link_count
        FROM base
        """
    )
    row = cur.fetchone()
    return {
        "total_meetings": row[0],
        "skipped_meetings": row[1],
        "applicable_meetings": row[2],
        "meetings_with_groups": row[3],
        "group_count": row[4],
        "utterance_link_count": row[5],
    }


def _load_integrity(cur: object) -> dict[str, int]:
    queries = {
        "skipped_with_groups": """
            SELECT COUNT(*)
            FROM session_groups sg
            JOIN meetings m ON m.mnts_id = sg.meeting_id
            WHERE m.meeting_type IN ('본회의', '소위원회')
               OR m.title ~ '(소위원회|조세소위|법안심사.*소위|예산결산.*소위|안건조정위원회)'
        """,
        "questioner_fk_missing": """
            SELECT COUNT(*)
            FROM session_groups sg
            LEFT JOIN members m ON m.mona_cd = sg.questioner_mona_cd
            WHERE m.mona_cd IS NULL
        """,
        "utterance_count_mismatch": """
            SELECT COUNT(*)
            FROM session_groups sg
            LEFT JOIN (
                SELECT session_group_id, COUNT(*) AS cnt
                FROM utterances
                WHERE session_group_id IS NOT NULL
                GROUP BY session_group_id
            ) u ON u.session_group_id = sg.id
            WHERE COALESCE(u.cnt, 0) <> sg.utterance_count
        """,
        "total_chars_mismatch": """
            SELECT COUNT(*)
            FROM session_groups sg
            LEFT JOIN (
                SELECT session_group_id, SUM(char_length(content)) AS chars
                FROM utterances
                WHERE session_group_id IS NOT NULL
                GROUP BY session_group_id
            ) u ON u.session_group_id = sg.id
            WHERE COALESCE(u.chars, 0) <> sg.total_chars
        """,
        "respondents_format_invalid": """
            SELECT COUNT(*)
            FROM session_groups sg
            WHERE respondents IS NULL
               OR jsonb_typeof(respondents) <> 'array'
               OR EXISTS (
                   SELECT 1
                   FROM jsonb_array_elements(respondents) AS item
                   WHERE jsonb_typeof(item) <> 'object'
                      OR NOT (item ? 'name')
                      OR NOT (item ? 'title')
               )
        """,
        "respondent_empty_groups": """
            SELECT COUNT(*) FROM session_groups WHERE jsonb_array_length(respondents) = 0
        """,
        "groups_with_50_plus_utterances": """
            SELECT COUNT(*) FROM session_groups WHERE utterance_count >= 50
        """,
        "groups_with_100_plus_utterances": """
            SELECT COUNT(*) FROM session_groups WHERE utterance_count >= 100
        """,
        "max_group_utterance_count": """
            SELECT COALESCE(MAX(utterance_count), 0) FROM session_groups
        """,
    }
    result: dict[str, int] = {}
    for key, sql in queries.items():
        cur.execute(sql)
        result[key] = cur.fetchone()[0]
    return result


def _render_markdown(result: SessionGroupValidationResult) -> str:
    success_pct = (
        result.meetings_with_groups / result.applicable_meetings * 100
        if result.applicable_meetings
        else 0
    )
    lines = [
        "# Session Groups Calibration",
        "",
        "This report measures automatic Q&A session_group generation on the",
        "current 10% utterance calibration load. This is a generation-rate and",
        "data-integrity check; semantic accuracy review remains in Slice 9.",
        "",
        "## Summary",
        "",
        f"- Meetings with utterances: {result.total_meetings}",
        f"- Skip-target meetings: {result.skipped_meetings}",
        f"- Applicable meetings: {result.applicable_meetings}",
        f"- Applicable meetings with groups: {result.meetings_with_groups} ({success_pct:.1f}%)",
        f"- Session groups: {result.group_count}",
        f"- Linked utterances: {result.utterance_link_count}",
        f"- Groups with no detected respondents: {result.respondent_empty_groups}",
        "",
        "## Semantic Review Candidates",
        "",
        f"- Groups with 50+ utterances: {result.groups_with_50_plus_utterances}",
        f"- Groups with 100+ utterances: {result.groups_with_100_plus_utterances}",
        f"- Largest group utterance count: {result.max_group_utterance_count}",
        "",
        "## Integrity",
        "",
        f"- Skip-target groups: {result.skipped_with_groups}",
        f"- Missing questioner FK refs: {result.questioner_fk_missing}",
        f"- utterance_count mismatches: {result.utterance_count_mismatch}",
        f"- total_chars mismatches: {result.total_chars_mismatch}",
        f"- Invalid respondents JSONB: {result.respondents_format_invalid}",
        "",
        "## By Meeting Type",
        "",
        "| Type | Meetings | Skipped | Applicable | Applicable with groups | Groups | Success |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in result.type_metrics:
        success = (
            f"{metric.applicable_success_pct}%"
            if metric.applicable_success_pct is not None
            else "-"
        )
        lines.append(
            f"| {metric.meeting_type} | {metric.meetings} | {metric.skipped} | "
            f"{metric.applicable} | {metric.applicable_with_groups} | "
            f"{metric.groups} | {success} |"
        )
    lines.append("")
    return "\n".join(lines)
