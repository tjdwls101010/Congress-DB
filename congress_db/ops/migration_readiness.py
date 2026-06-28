"""Hosted Postgres migration readiness report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.db import get_conn

DEFAULT_MIGRATION_READINESS_REPORT = Path("docs/ops/MIGRATION-READINESS.md")
READY = "ready_for_human_review"
NOT_READY = "not_ready_for_human_review"
SANITY_KEYS = frozenset({"S1", "S2", "S4a", "S7"})
CORE_TABLES = (
    "members",
    "bills",
    "bill_relations",
    "bill_lead_proposers",
    "bill_coproposers",
    "votes",
)


@dataclass(frozen=True)
class MigrationReadinessReport:
    """Hosted Postgres migration human-review gate report."""

    recommendation: str
    blockers: tuple[str, ...]
    latest_backfill_run: Mapping[str, Any] | None
    dead_letter_counts: tuple[Mapping[str, Any], ...]
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
        row_counts = _load_row_counts(cur)

    sanity_signal = _extract_sanity_signal(latest_backfill)
    data_completeness_signal = _extract_data_completeness_signal(latest_backfill)
    blockers = _blockers(
        latest_backfill=latest_backfill,
        dead_letters=dead_letters,
        sanity_signal=sanity_signal,
        data_completeness_signal=data_completeness_signal,
    )
    warnings = _warnings(data_completeness_signal)
    return MigrationReadinessReport(
        recommendation=NOT_READY if blockers else READY,
        blockers=tuple(blockers),
        latest_backfill_run=latest_backfill,
        dead_letter_counts=tuple(dead_letters),
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
          AND (
              summary->>'entrypoint' = 'ingest'
              OR (
                  summary #> '{stages,sanity_check}' IS NOT NULL
                  AND summary #> '{stages,data_completeness}' IS NOT NULL
              )
              OR summary->>'test' = 'migration_readiness'
          )
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


def _extract_data_completeness_signal(
    latest_backfill: Mapping[str, Any] | None,
) -> dict[str, Any]:
    completeness = _stage(latest_backfill, "data_completeness")
    metrics = completeness.get("metrics") if isinstance(completeness, Mapping) else None
    if not isinstance(metrics, Sequence) or isinstance(metrics, (str, bytes)):
        return {"available": False, "metric_count": 0}
    return {"available": True, "metric_count": len(metrics)}


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
    if not sanity_signal.get("available") or sanity_signal.get("missing_keys"):
        blockers.append("sanity_check signal unavailable")
    if not data_completeness_signal.get("available"):
        blockers.append("data_completeness signal unavailable")
    return blockers


def _warnings(
    data_completeness_signal: Mapping[str, Any],
) -> list[str]:
    return []


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

    lines.extend(["", "## Sanity And Completeness", ""])
    lines.append(f"- sanity_check: `{report.sanity_signal}`")
    lines.append(f"- data_completeness: `{report.data_completeness_signal}`")

    lines.extend(["", "## Row Counts", "", "| Table | Rows |", "|---|---:|"])
    for table, count in report.row_counts.items():
        lines.append(f"| `{table}` | {count} |")
    lines.append("")
    return "\n".join(lines)
