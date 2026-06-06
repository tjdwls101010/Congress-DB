#!/usr/bin/env python3
"""bill_relations 대안 관계 백필 CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from congress_db.ingest.backfill import (
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    run_staged_ingest,
)
from congress_db.ingest.ingest_bill_relations import ingest_bill_relations


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill bill_relations from likms.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--worker-count", type=int, default=20)
    args = parser.parse_args()

    def run_bill_relations() -> StageResult:
        result = ingest_bill_relations(limit=args.limit, worker_count=args.worker_count)
        summary = asdict(result)
        failures = summary.pop("failures")
        dead_letters = tuple(
            DeadLetterDraft(
                source="bill_relations",
                stage="bill_relations",
                item_key=str(failure["bill_id"]),
                payload={"bill_id": failure["bill_id"], "reason": failure["reason"]},
                error=f"{failure['reason']}: {failure['error']}",
            )
            for failure in failures
        )
        return StageResult(summary=summary, dead_letters=dead_letters)

    run = run_staged_ingest(
        mode="backfill",
        stages=(BackfillStage("bill_relations", run_bill_relations),),
        run_metadata={"entrypoint": "ingest_bill_relations", "issue": 72},
    )
    summary = run.stage_summaries["bill_relations"]
    print(
        "Backfilled bill relations: "
        f"run_id={run.run_id} "
        f"status={run.status} "
        f"target={summary['target_count']} "
        f"relations={summary['relation_count']} "
        f"failures={summary['failure_count']} "
        f"dead_letters={run.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
