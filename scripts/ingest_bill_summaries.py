#!/usr/bin/env python3
"""기존 bills의 결측 summary 백필 CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from congress_db.ingest.backfill import (
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    run_staged_ingest,
)
from congress_db.ingest.ingest_bills import backfill_missing_bill_summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing bill summaries.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--worker-count", type=int, default=None)
    args = parser.parse_args()

    def run_summary_backfill() -> StageResult:
        result = backfill_missing_bill_summaries(
            limit=args.limit,
            summary_worker_count=args.worker_count,
        )
        summary = asdict(result)
        failures = summary.pop("summary_failures")
        dead_letters = tuple(
            DeadLetterDraft(
                source="bills.summary",
                stage="fetch",
                item_key=str(failure["bill_no"]),
                payload={"bill_no": failure["bill_no"]},
                error=str(failure["error"]),
            )
            for failure in failures
        )
        return StageResult(summary=summary, dead_letters=dead_letters)

    run = run_staged_ingest(
        mode="backfill",
        stages=(BackfillStage("bills_summary_backfill", run_summary_backfill),),
        run_metadata={"entrypoint": "ingest_bill_summaries", "issue": 84},
    )
    summary = run.stage_summaries["bills_summary_backfill"]
    print(
        "Backfilled bill summaries: "
        f"run_id={run.run_id} "
        f"status={run.status} "
        f"target={summary['target_count']} "
        f"updated={summary['updated_count']} "
        f"accepted_gap={summary['accepted_gap_count']} "
        f"no_data={summary['no_data_count']} "
        f"errors={summary['error_count']} "
        f"remaining_missing={summary['remaining_missing_count']} "
        f"dead_letters={run.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
