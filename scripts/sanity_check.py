#!/usr/bin/env python3
"""통합 sanity check CLI."""

from __future__ import annotations

from congress_db.ops.sanity_check import run_sanity_check


def main() -> None:
    result = run_sanity_check()
    print(
        "Generated sanity check: "
        f"sections={len(result.sections)} "
        f"members={result.row_counts.get('members', 0)} "
        f"bills={result.row_counts.get('bills', 0)} "
        f"utterances={result.row_counts.get('utterances', 0)} "
        f"fts={result.fts_decision.selected}"
    )


if __name__ == "__main__":
    main()
