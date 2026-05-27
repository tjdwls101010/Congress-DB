#!/usr/bin/env python3
"""회의록 DOM 구조 다층 샘플 검증 CLI."""

from __future__ import annotations

import argparse

from congress_db.validate_minutes_dom import validate_minutes_dom


def main() -> None:
    parser = argparse.ArgumentParser(description="회의록 DOM 구조 다층 검증")
    parser.add_argument("--per-type", type=int, default=10)
    args = parser.parse_args()

    result = validate_minutes_dom(per_type=args.per_type)
    print(
        "Validated minutes DOM: "
        f"checked={result.checked_count} "
        f"errors={result.error_count} "
        f"parse_failures={result.parse_failure_count}"
    )


if __name__ == "__main__":
    main()
