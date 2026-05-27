#!/usr/bin/env python3
"""session_group 정확도 검증 아티팩트 생성 CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from congress_db.evaluate_session_groups import (
    DEFAULT_EVAL_DIR,
    DEFAULT_EVAL_REPORT,
    generate_session_group_eval,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Q&A session_group 정확도 검증")
    parser.add_argument("--per-type", type=int, default=5)
    parser.add_argument("--min-groups", type=int, default=5)
    parser.add_argument("--max-groups", type=int, default=80)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVAL_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_EVAL_REPORT)
    parser.add_argument(
        "--overwrite-labels",
        action="store_true",
        help="existing labels.csv를 자동 후보로 덮어쓴다",
    )
    args = parser.parse_args()

    result = generate_session_group_eval(
        output_dir=args.output_dir,
        report_path=args.report_path,
        per_type=args.per_type,
        min_groups=args.min_groups,
        max_groups=args.max_groups,
        overwrite=args.overwrite_labels,
    )
    print(
        "Evaluated session groups: "
        f"correct={result.correct_count} "
        f"incorrect={result.incorrect_count} "
        f"missing={result.missing_count} "
        f"pending={result.pending_count} "
        f"precision={result.precision if result.precision is not None else 'pending'} "
        f"recall={result.recall if result.recall is not None else 'pending'}"
    )


if __name__ == "__main__":
    main()
