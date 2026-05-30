#!/usr/bin/env python3
"""로컬 100% 백필 CLI."""

from __future__ import annotations

from congress_db.backfill import run_backfill
from congress_db.progress import safe_print


def main() -> None:
    result = run_backfill()
    safe_print(
        "Completed backfill: "
        f"run_id={result.run_id} "
        f"status={result.status} "
        f"stages={len(result.stage_summaries)} "
        f"dead_letters={result.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
