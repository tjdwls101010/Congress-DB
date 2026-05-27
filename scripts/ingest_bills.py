#!/usr/bin/env python3
"""bills + bill_coproposers 적재 CLI."""

from __future__ import annotations

import argparse

from congress_db.ingest_bills import ingest_bills


def main() -> None:
    parser = argparse.ArgumentParser(description="22대 법안 10% 적재")
    parser.add_argument("--limit-pct", type=float, default=0.1)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    result = ingest_bills(limit_pct=args.limit_pct, page_size=args.page_size)
    age = (
        next(iter(result.age_param_used.items()))
        if result.age_param_used
        else ("age", "none")
    )
    print(
        "Ingested bills: "
        f"fetched={result.fetched_count}/{result.total_count} "
        f"target={result.target_count} "
        f"bills={result.upserted_bills} "
        f"lead_proposers={result.upserted_lead_proposers} "
        f"coproposers={result.upserted_coproposers} "
        f"member_refs={result.ensured_member_refs} "
        f"summaries={result.summary_success_count} "
        f"summary_errors={result.summary_error_count} "
        f"workers={result.selected_worker_count} "
        f"{age[0]}={age[1]}"
    )


if __name__ == "__main__":
    main()
