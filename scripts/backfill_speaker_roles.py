#!/usr/bin/env python3
"""기존 발언 speaker_role 백필 CLI."""

from __future__ import annotations

import argparse

from congress_db.core.progress import safe_print
from congress_db.ingest.speaker_roles import normalize_speaker_roles


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill utterances.speaker_role.")
    parser.add_argument(
        "--other-threshold",
        type=int,
        default=500,
        help="Minimum utterance count for printing high-frequency 기타 titles.",
    )
    args = parser.parse_args()

    result = normalize_speaker_roles(other_threshold=args.other_threshold)
    safe_print(
        "Backfilled speaker roles: "
        f"utterances={result.utterance_count} "
        f"updated={result.updated_utterance_count} "
        f"null_speaker_role={result.null_speaker_role_count}"
    )
    safe_print("Role distribution:")
    for role, count in result.role_distribution.items():
        safe_print(f"  {role}: {count}")
    safe_print(f"High-frequency 기타 titles (n>={args.other_threshold}):")
    for row in result.high_frequency_other_titles:
        safe_print(
            "  "
            f"{row.speaker_title}\t"
            f"n_total={row.n_utterances}\t"
            f"n_no_mona={row.n_no_mona}\t"
            f"n_mona={row.n_mona}"
        )


if __name__ == "__main__":
    main()
