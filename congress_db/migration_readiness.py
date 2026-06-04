"""Hosted Postgres migration readiness report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .db import get_conn
from .evaluate_session_groups import (
    DEFAULT_EVAL_DIR,
    DEFAULT_MEETING_TYPES,
    evaluate_labels,
)
from .utterance_mapping_quality import (
    MemberUtteranceMappingQuality,
    load_member_utterance_mapping_quality,
)

DEFAULT_MIGRATION_READINESS_REPORT = Path("docs/MIGRATION-READINESS.md")
READY = "ready_for_human_review"
NOT_READY = "not_ready_for_human_review"
MAPPING_RATE_REGRESSION_WARNING_PCT = 1.0
SANITY_KEYS = frozenset({"S1", "S2", "S3", "S4a", "S4b", "S5", "S6", "S7"})
CORE_TABLES = (
    "members",
    "bills",
    "bill_lead_proposers",
    "bill_coproposers",
    "votes",
    "meetings",
    "meeting_bills",
    "utterances",
    "session_groups",
)


@dataclass(frozen=True)
class MigrationReadinessReport:
    """Hosted Postgres migration human-review gate report."""

    recommendation: str
    blockers: tuple[str, ...]
    latest_backfill_run: Mapping[str, Any] | None
    dead_letter_counts: tuple[Mapping[str, Any], ...]
    session_group_integrity: Mapping[str, int]
    session_group_integrity_error_count: int
    session_group_semantic_accuracy: Mapping[str, Any]
    sanity_signal: Mapping[str, Any]
    data_completeness_signal: Mapping[str, Any]
    warnings: tuple[str, ...]
    row_counts: Mapping[str, int]


def generate_migration_readiness_report(
    output_path: Path = DEFAULT_MIGRATION_READINESS_REPORT,
) -> MigrationReadinessReport:
    """현재 로컬 DB가 hosted Postgres migration review 준비 상태인지 리포트한다."""
    report = load_migration_readiness()
    render_migration_readiness_report(report, output_path)
    return report


def load_migration_readiness() -> MigrationReadinessReport:
    """readiness 판단에 필요한 신호를 DB에서 읽는다."""
    with get_conn() as conn, conn.cursor() as cur:
        latest_backfill = _load_latest_backfill(cur)
        dead_letters = _load_unresolved_dead_letters(cur)
        integrity = _load_session_group_integrity(cur)
        row_counts = _load_row_counts(cur)
        member_mapping = load_member_utterance_mapping_quality(cur, sample_limit=0)
        previous_mapping_rate = _load_previous_mapping_rate(cur, latest_backfill)

    sanity_signal = _extract_sanity_signal(latest_backfill)
    semantic_accuracy = _load_session_group_semantic_accuracy()
    data_completeness_signal = _extract_data_completeness_signal(
        latest_backfill,
        member_mapping=member_mapping,
        previous_mapping_rate=previous_mapping_rate,
    )
    integrity_errors = sum(integrity.values())
    blockers = _blockers(
        latest_backfill=latest_backfill,
        dead_letters=dead_letters,
        integrity_errors=integrity_errors,
        sanity_signal=sanity_signal,
        data_completeness_signal=data_completeness_signal,
    )
    warnings = _warnings(data_completeness_signal, semantic_accuracy)
    return MigrationReadinessReport(
        recommendation=NOT_READY if blockers else READY,
        blockers=tuple(blockers),
        latest_backfill_run=latest_backfill,
        dead_letter_counts=tuple(dead_letters),
        session_group_integrity=integrity,
        session_group_integrity_error_count=integrity_errors,
        session_group_semantic_accuracy=semantic_accuracy,
        sanity_signal=sanity_signal,
        data_completeness_signal=data_completeness_signal,
        warnings=tuple(warnings),
        row_counts=row_counts,
    )


def render_migration_readiness_report(
    report: MigrationReadinessReport,
    output_path: Path,
) -> None:
    """readiness 리포트를 Markdown으로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(report))


def _load_latest_backfill(cur: object) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT id, status, started_at, finished_at, summary, error
        FROM ingest_runs
        WHERE mode = 'backfill'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "status": row[1],
        "started_at": row[2],
        "finished_at": row[3],
        "summary": row[4] or {},
        "error": row[5],
    }


def _load_unresolved_dead_letters(cur: object) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT source, stage, status, COUNT(*) AS count
        FROM dead_letters
        WHERE status IN ('pending', 'retrying', 'blocked')
        GROUP BY source, stage, status
        ORDER BY count DESC, source, stage, status
        """
    )
    return [
        {"source": row[0], "stage": row[1], "status": row[2], "count": row[3]}
        for row in cur.fetchall()
    ]


def _load_session_group_integrity(cur: object) -> dict[str, int]:
    queries = {
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
            FROM session_groups
            WHERE respondents IS NULL OR jsonb_typeof(respondents) <> 'array'
        """,
        "respondent_empty_groups": """
            SELECT COUNT(*)
            FROM session_groups
            WHERE respondents IS NULL OR jsonb_array_length(respondents) = 0
        """,
    }
    result: dict[str, int] = {}
    for key, sql in queries.items():
        cur.execute(sql)
        result[key] = cur.fetchone()[0]
    return result


def _load_row_counts(cur: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in CORE_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cur.fetchone()[0]
    return counts


def _extract_sanity_signal(latest_backfill: Mapping[str, Any] | None) -> dict[str, Any]:
    sanity = _stage(latest_backfill, "sanity_check")
    sections = sanity.get("sections") if isinstance(sanity, Mapping) else None
    if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes)):
        return {"available": False, "section_keys": (), "missing_keys": tuple(sorted(SANITY_KEYS))}
    section_keys = {
        str(section.get("key"))
        for section in sections
        if isinstance(section, Mapping) and section.get("key")
    }
    missing = tuple(sorted(SANITY_KEYS - section_keys))
    return {
        "available": True,
        "section_keys": tuple(sorted(section_keys)),
        "missing_keys": missing,
    }


def _load_previous_mapping_rate(
    cur: object,
    latest_backfill: Mapping[str, Any] | None,
) -> float | None:
    if latest_backfill is None:
        return None
    cur.execute(
        """
        SELECT summary
        FROM ingest_runs
        WHERE mode = 'backfill'
          AND status = 'success'
          AND id <> %s
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (latest_backfill["id"],),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _extract_data_completeness_mapping_rate({"summary": row[0] or {}})


def _load_session_group_semantic_accuracy() -> dict[str, Any]:
    labels_path = DEFAULT_EVAL_DIR / "labels.csv"
    if not labels_path.exists():
        return {"available": False, "labels_path": str(labels_path)}
    result = evaluate_labels(labels_path)
    evaluated_types = {row.meeting_type for row in result.by_type}
    return {
        "available": True,
        "labels_path": str(labels_path),
        "complete": result.is_complete,
        "missing_meeting_types": tuple(
            meeting_type
            for meeting_type in DEFAULT_MEETING_TYPES
            if meeting_type not in evaluated_types
        ),
        "correct_count": result.correct_count,
        "incorrect_count": result.incorrect_count,
        "missing_count": result.missing_count,
        "pending_count": result.pending_count,
        "reviewed_count": result.reviewed_count,
        "agent_labeled_count": result.agent_labeled_count,
        "human_labeled_count": result.human_labeled_count,
        "precision": result.precision,
        "recall": result.recall,
        "by_type": [
            {
                "meeting_type": row.meeting_type,
                "correct_count": row.correct_count,
                "incorrect_count": row.incorrect_count,
                "missing_count": row.missing_count,
                "pending_count": row.pending_count,
                "precision": row.precision,
                "recall": row.recall,
            }
            for row in result.by_type
        ],
    }


def _extract_data_completeness_signal(
    latest_backfill: Mapping[str, Any] | None,
    *,
    member_mapping: MemberUtteranceMappingQuality,
    previous_mapping_rate: float | None,
) -> dict[str, Any]:
    completeness = _stage(latest_backfill, "data_completeness")
    metrics = completeness.get("metrics") if isinstance(completeness, Mapping) else None
    if not isinstance(metrics, Sequence) or isinstance(metrics, (str, bytes)):
        signal: dict[str, Any] = {"available": False, "metric_count": 0}
    else:
        signal = {"available": True, "metric_count": len(metrics)}
        latest_summary_rate = _metric_value(
            metrics,
            "member_titled_utterance_actionable_mapping_rate_pct",
        )
        if latest_summary_rate is not None:
            signal["member_titled_utterance_actionable_mapping_rate_pct"] = latest_summary_rate

    signal.setdefault("member_titled_utterances_total", member_mapping.total_utterances)
    signal.setdefault("unmapped_member_titled_utterances", member_mapping.unmapped_utterances)
    signal.setdefault("ambiguous_name_unmapped_utterances", member_mapping.ambiguous_name_unmapped)
    signal.setdefault(
        "member_titled_utterance_mapping_rate_pct",
        member_mapping.mapping_rate_pct,
    )
    signal.setdefault(
        "member_titled_utterance_actionable_mapping_rate_pct",
        member_mapping.actionable_mapping_rate_pct,
    )
    signal["previous_actionable_mapping_rate_pct"] = previous_mapping_rate
    current_rate = signal.get("member_titled_utterance_actionable_mapping_rate_pct")
    if isinstance(current_rate, (int, float)) and previous_mapping_rate is not None:
        delta = round(float(current_rate) - previous_mapping_rate, 2)
        signal["actionable_mapping_rate_delta_pct"] = delta
        signal["mapping_rate_regression_warning"] = (
            delta <= -MAPPING_RATE_REGRESSION_WARNING_PCT
        )
    else:
        signal["actionable_mapping_rate_delta_pct"] = None
        signal["mapping_rate_regression_warning"] = False
    return signal


def _extract_data_completeness_mapping_rate(
    latest_backfill: Mapping[str, Any] | None,
) -> float | None:
    completeness = _stage(latest_backfill, "data_completeness")
    metrics = completeness.get("metrics") if isinstance(completeness, Mapping) else None
    if not isinstance(metrics, Sequence) or isinstance(metrics, (str, bytes)):
        return None
    return _metric_value(metrics, "member_titled_utterance_actionable_mapping_rate_pct")


def _metric_value(metrics: Sequence[Any], name: str) -> float | None:
    for metric in metrics:
        if not isinstance(metric, Mapping) or metric.get("name") != name:
            continue
        value = metric.get("value")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
    return None


def _stage(latest_backfill: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    if latest_backfill is None:
        return {}
    summary = latest_backfill.get("summary")
    if not isinstance(summary, Mapping):
        return {}
    stages = summary.get("stages")
    if not isinstance(stages, Mapping):
        return {}
    stage = stages.get(name)
    return stage if isinstance(stage, Mapping) else {}


def _blockers(
    *,
    latest_backfill: Mapping[str, Any] | None,
    dead_letters: Sequence[Mapping[str, Any]],
    integrity_errors: int,
    sanity_signal: Mapping[str, Any],
    data_completeness_signal: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if latest_backfill is None:
        blockers.append("no backfill run found")
    elif latest_backfill.get("status") != "success":
        blockers.append(f"latest backfill status is {latest_backfill.get('status')}")

    unresolved_count = sum(int(row["count"]) for row in dead_letters)
    if unresolved_count:
        blockers.append(f"unresolved dead letters remain: {unresolved_count}")
    if integrity_errors:
        blockers.append(f"session group integrity errors remain: {integrity_errors}")
    if not sanity_signal.get("available") or sanity_signal.get("missing_keys"):
        blockers.append("sanity_check signal unavailable")
    if not data_completeness_signal.get("available"):
        blockers.append("data_completeness signal unavailable")
    return blockers


def _warnings(
    data_completeness_signal: Mapping[str, Any],
    semantic_accuracy: Mapping[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if data_completeness_signal.get("mapping_rate_regression_warning"):
        delta = data_completeness_signal.get("actionable_mapping_rate_delta_pct")
        previous = data_completeness_signal.get("previous_actionable_mapping_rate_pct")
        current = data_completeness_signal.get(
            "member_titled_utterance_actionable_mapping_rate_pct"
        )
        warnings.append(
            "member-titled utterance mapping rate dropped "
            f"{delta} percentage points from previous success run "
            f"(previous={previous}, current={current})"
        )
    if not semantic_accuracy.get("available"):
        warnings.append("session_group semantic accuracy labels are unavailable")
    elif not semantic_accuracy.get("complete"):
        warnings.append(
            "session_group semantic accuracy review is incomplete "
            f"(pending={semantic_accuracy.get('pending_count')}, "
            f"reviewed={semantic_accuracy.get('reviewed_count')})"
        )
    elif semantic_accuracy.get("agent_labeled_count"):
        warnings.append(
            "session_group semantic accuracy is based on agent first-pass labels; "
            "PM verification remains before treating it as final"
        )
    missing_types = semantic_accuracy.get("missing_meeting_types")
    if missing_types:
        warnings.append(
            "session_group semantic accuracy has no sampled meetings for: "
            + ", ".join(str(item) for item in missing_types)
        )
    return warnings


def _render_markdown(report: MigrationReadinessReport) -> str:
    lines = [
        "# Hosted Postgres Migration Readiness",
        "",
        f"Recommendation: `{report.recommendation}`",
        "",
        "## Blockers",
        "",
    ]
    if report.blockers:
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    else:
        lines.append("- None")

    lines.extend(["", "## Warnings", ""])
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("- None")

    lines.extend(["", "## Latest Backfill Run", ""])
    if report.latest_backfill_run is None:
        lines.append("- None")
    else:
        run = report.latest_backfill_run
        lines.extend(
            [
                f"- id: `{run['id']}`",
                f"- status: `{run['status']}`",
                f"- started_at: `{run['started_at']}`",
                f"- finished_at: `{run['finished_at']}`",
                f"- error: `{run['error']}`",
            ]
        )

    lines.extend(["", "## Unresolved Dead Letters", ""])
    if report.dead_letter_counts:
        lines.extend(["| Source | Stage | Status | Count |", "|---|---|---|---:|"])
        for row in report.dead_letter_counts:
            lines.append(
                f"| `{row['source']}` | `{row['stage']}` | `{row['status']}` | {row['count']} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Session Group Integrity", ""])
    lines.extend(["| Metric | Count |", "|---|---:|"])
    for key, value in report.session_group_integrity.items():
        lines.append(f"| `{key}` | {value} |")

    lines.extend(["", "## Session Group Semantic Accuracy", ""])
    lines.append(f"- signal: `{report.session_group_semantic_accuracy}`")

    lines.extend(["", "## Sanity And Completeness", ""])
    lines.append(f"- sanity_check: `{report.sanity_signal}`")
    lines.append(f"- data_completeness: `{report.data_completeness_signal}`")

    lines.extend(["", "## Row Counts", "", "| Table | Rows |", "|---|---:|"])
    for table, count in report.row_counts.items():
        lines.append(f"| `{table}` | {count} |")
    lines.append("")
    return "\n".join(lines)
