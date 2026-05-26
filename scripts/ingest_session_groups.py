#!/usr/bin/env python3
"""session_groups 캘리브레이션 적재 CLI."""

from __future__ import annotations

import argparse

from congress_db.session_groups import ingest_session_groups


def main() -> None:
    parser = argparse.ArgumentParser(description="Q&A session_groups 캘리브레이션 적재")
    parser.add_argument("--calibration-limit", type=int, default=500)
    args = parser.parse_args()

    result = ingest_session_groups(calibration_limit=args.calibration_limit)
    print(
        "Ingested session groups: "
        f"meetings={result.meeting_count} "
        f"skipped={result.skipped_meeting_count} "
        f"groups={result.group_count} "
        f"utterance_links={result.utterance_link_count}"
    )


if __name__ == "__main__":
    main()
