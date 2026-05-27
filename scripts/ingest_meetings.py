#!/usr/bin/env python3
"""meetings + agenda_items + meeting_bills 캘리브레이션 적재 CLI."""

from __future__ import annotations

import argparse

from congress_db.ingest_meetings import ingest_meetings


def main() -> None:
    parser = argparse.ArgumentParser(description="22대 회의 메타 캘리브레이션 적재")
    parser.add_argument("--calibration-limit", type=int, default=500)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    result = ingest_meetings(
        calibration_limit=args.calibration_limit,
        page_size=args.page_size,
    )
    print(
        "Ingested meetings: "
        f"meetings={result.meeting_count}/{result.total_count} "
        f"target={result.target_count} "
        f"agenda_items={result.agenda_item_count} "
        f"meeting_bills={result.meeting_bill_count} "
        f"workers={result.selected_worker_count}"
    )


if __name__ == "__main__":
    main()
