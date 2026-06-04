#!/usr/bin/env python3
"""votes 적재 CLI."""

from __future__ import annotations

import argparse

from congress_db.ingest_votes import ingest_votes


def main() -> None:
    parser = argparse.ArgumentParser(description="22대 본회의 표결 10% 적재")
    parser.add_argument("--limit-pct", type=float, default=0.1)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    result = ingest_votes(limit_pct=args.limit_pct, page_size=args.page_size)
    age = (
        next(iter(result.age_param_used.items()))
        if result.age_param_used
        else ("age", "none")
    )
    print(
        "Ingested votes: "
        f"vote_bills={result.vote_bill_count}/{result.total_bill_count} "
        f"target={result.target_bill_count} "
        f"vote_rows={result.vote_row_count} "
        f"bill_refs={result.upserted_bill_refs} "
        f"member_refs={result.ensured_member_refs} "
        f"votes={result.upserted_votes} "
        f"workers={result.selected_worker_count} "
        f"tolerated_distribution_mismatches={result.tolerated_distribution_mismatches} "
        f"failed_vote_bills={result.failed_vote_bill_count} "
        f"{age[0]}={age[1]}"
    )


if __name__ == "__main__":
    main()
