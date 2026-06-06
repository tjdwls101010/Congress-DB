#!/usr/bin/env python3
"""데이터 완성도 follow-up CLI."""

from __future__ import annotations

from congress_db.ops.data_completeness import generate_data_completeness_report


def main() -> None:
    report = generate_data_completeness_report()
    print(
        "Generated data completeness report: "
        f"metrics={len(report.metrics)} "
        f"tables={len(report.tables)}"
    )


if __name__ == "__main__":
    main()
