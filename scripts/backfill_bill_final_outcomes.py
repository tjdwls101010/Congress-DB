#!/usr/bin/env python3
"""bill_final_outcomes + propose_dt ALLBILL 백필 CLI."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict

from congress_db.core.api_client import fetch_endpoint
from congress_db.ingest.backfill import (
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    run_staged_ingest,
)
from congress_db.ingest.bill_final_outcomes import (
    FetchAllbill,
    backfill_bill_final_outcomes,
)


def build_bill_final_outcomes_stage(
    *,
    limit: int | None = None,
    bill_nos: Sequence[str] | None = None,
    fetch_allbill: FetchAllbill = fetch_endpoint,
) -> BackfillStage:
    """ALLBILL 백필 stage를 구성한다."""

    def run_bill_final_outcomes() -> StageResult:
        result = backfill_bill_final_outcomes(
            limit=limit,
            bill_nos=bill_nos,
            fetch_allbill=fetch_allbill,
        )
        dead_letters = tuple(
            DeadLetterDraft(
                source="bill_final_outcomes",
                stage="fetch",
                item_key=failure.bill_no,
                payload={
                    "bill_id": failure.bill_id,
                    "bill_no": failure.bill_no,
                    "proc_result": failure.proc_result,
                    "reason": failure.reason,
                },
                error=f"{failure.reason}: {failure.error}",
            )
            for failure in result.failures
        )
        return StageResult(summary=asdict(result), dead_letters=dead_letters)

    return BackfillStage("bill_final_outcomes", run_bill_final_outcomes)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill bill_final_outcomes and missing bills.propose_dt from ALLBILL."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--bill-no", action="append", default=None)
    args = parser.parse_args()

    run = run_staged_ingest(
        mode="backfill",
        stages=(
            build_bill_final_outcomes_stage(
                limit=args.limit,
                bill_nos=args.bill_no,
            ),
        ),
        run_metadata={"entrypoint": "backfill_bill_final_outcomes", "issue": 86},
    )
    summary = run.stage_summaries["bill_final_outcomes"]
    print(
        "Backfilled bill final outcomes: "
        f"run_id={run.run_id} "
        f"status={run.status} "
        f"targets={summary['target_count']} "
        f"skipped={summary['skipped_count']} "
        f"fetched={summary['fetched_count']}/{summary['fetch_target_count']} "
        f"outcomes={summary['outcome_upserted_count']} "
        f"propose_dt_updates={summary['propose_dt_updated_count']} "
        f"accepted_gaps={summary['accepted_gap_count']} "
        f"no_data={summary['no_data_count']} "
        f"errors={summary['error_count']} "
        f"dead_letters={run.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
