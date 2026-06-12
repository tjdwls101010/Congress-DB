#!/usr/bin/env python3
"""bill_documents BILLRCPV2 URL inventory 백필 CLI."""

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
from congress_db.ingest.bill_documents import (
    FetchBillDocuments,
    backfill_bill_documents,
)


def build_bill_documents_stage(
    *,
    limit: int | None = None,
    bill_ids: Sequence[str] | None = None,
    fetch_billrcpv2: FetchBillDocuments = fetch_endpoint,
) -> BackfillStage:
    """BILLRCPV2 bill_documents 백필 stage를 구성한다."""

    def run_bill_documents() -> StageResult:
        result = backfill_bill_documents(
            limit=limit,
            bill_ids=bill_ids,
            fetch_billrcpv2=fetch_billrcpv2,
        )
        dead_letters = tuple(
            DeadLetterDraft(
                source="bill_documents",
                stage="fetch",
                item_key=failure.bill_id,
                payload={
                    "bill_id": failure.bill_id,
                    "bill_no": failure.bill_no,
                    "reason": failure.reason,
                },
                error=f"{failure.reason}: {failure.error}",
            )
            for failure in result.failures
        )
        return StageResult(summary=asdict(result), dead_letters=dead_letters)

    return BackfillStage("bill_documents", run_bill_documents)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill bill_documents URL inventory from BILLRCPV2."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--bill-id", action="append", default=None)
    args = parser.parse_args()

    run = run_staged_ingest(
        mode="backfill",
        stages=(
            build_bill_documents_stage(
                limit=args.limit,
                bill_ids=args.bill_id,
            ),
        ),
        run_metadata={"entrypoint": "backfill_bill_documents", "issue": 96},
    )
    summary = run.stage_summaries["bill_documents"]
    print(
        "Backfilled bill documents: "
        f"run_id={run.run_id} "
        f"status={run.status} "
        f"targets={summary['target_count']} "
        f"fetched={summary['fetched_count']}/{summary['fetch_target_count']} "
        f"documents={summary['document_upserted_count']} "
        f"bill_text={summary['bill_text_count']} "
        f"cost_estimate={summary['cost_estimate_count']} "
        f"no_data={summary['no_data_count']} "
        f"errors={summary['error_count']} "
        f"dead_letters={run.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
