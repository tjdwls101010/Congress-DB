#!/usr/bin/env python3
"""공식 단일 수집 CLI."""

from __future__ import annotations

import argparse

from congress_db.ingest_command import run_ingest
from congress_db.progress import safe_print


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the official Congress-DB ingest command.")
    parser.add_argument(
        "--mode",
        choices=("auto", "backfill", "incremental"),
        default="auto",
        help="Execution mode. Default auto chooses from local DB state.",
    )
    parser.add_argument(
        "--force-meeting-id",
        action="append",
        default=(),
        type=int,
        help="Meeting mnts_id to rescrape/regroup during incremental sync.",
    )
    args = parser.parse_args()

    result = run_ingest(mode=args.mode, force_meeting_ids=tuple(args.force_meeting_id))
    safe_print(
        "Completed ingest: "
        f"mode={result.mode} "
        f"run_id={result.run_id} "
        f"status={result.status} "
        f"stages={len(result.stage_summaries)} "
        f"dead_letters={result.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
