#!/usr/bin/env python3
"""meetings + meeting_bills 캘리브레이션 적재 CLI."""

from __future__ import annotations

import argparse

from congress_db.ingest.ingest_meetings import ingest_meetings


def main() -> None:
    parser = argparse.ArgumentParser(description="22대 회의 메타 캘리브레이션 적재")
    parser.add_argument("--calibration-limit", type=int, default=500)
    parser.add_argument("--page-size", type=int, default=1000)
    args = parser.parse_args()

    result = ingest_meetings(
        calibration_limit=args.calibration_limit,
        page_size=args.page_size,
    )
    print(
        "Ingested meetings: "
        f"meetings={result.meeting_count}/{result.total_count} "
        f"target={result.target_count} "
        f"agenda_candidates={result.agenda_candidate_count} "
        f"meeting_bills={result.meeting_bill_count} "
        f"new={len(result.new_meeting_ids)} "
        f"changed={len(result.changed_meeting_ids)} "
        f"stale={len(result.stale_meeting_ids)} "
        f"html_unavailable={len(result.html_unavailable_mnts_ids)} "
        f"web_only={len(result.web_only_mnts_ids)} "
        f"openapi_only={len(result.openapi_only_mnts_ids)} "
        f"workers={result.selected_worker_count}"
    )


if __name__ == "__main__":
    main()
