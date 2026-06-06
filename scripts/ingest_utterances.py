#!/usr/bin/env python3
"""utterances 캘리브레이션 적재 CLI."""

from __future__ import annotations

import argparse

from congress_db.ingest.ingest_utterances import ingest_utterances


def main() -> None:
    parser = argparse.ArgumentParser(description="회의록 본문 캘리브레이션 적재")
    parser.add_argument("--calibration-limit", type=int, default=500)
    args = parser.parse_args()

    result = ingest_utterances(calibration_limit=args.calibration_limit)
    print(
        "Ingested utterances: "
        f"meetings={result.scraped_meeting_count}/{result.meeting_count} "
        f"utterances={result.utterance_count} "
        f"member_mapped={result.member_mapped_count} "
        f"retries={result.retry_count} "
        f"retried_meetings={result.retried_meeting_count} "
        f"errors={result.scrape_error_count} "
        f"workers={result.selected_worker_count}"
    )
    for error in result.sample_errors:
        print(f"  error: {error}")


if __name__ == "__main__":
    main()
