#!/usr/bin/env python3
"""Hosted Postgres migration readiness report CLI."""

from __future__ import annotations

from congress_db.ops.migration_readiness import generate_migration_readiness_report


def main() -> None:
    report = generate_migration_readiness_report()
    print(
        "Generated migration readiness report: "
        f"recommendation={report.recommendation} "
        f"blockers={len(report.blockers)}"
    )


if __name__ == "__main__":
    main()
