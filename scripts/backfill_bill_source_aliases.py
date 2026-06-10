#!/usr/bin/env python3
"""bill_source_aliases source alias 백필 CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from congress_db.ingest.backfill import (
    BackfillStage,
    DeadLetterDraft,
    StageResult,
    run_staged_ingest,
)
from congress_db.ingest.bill_source_aliases import resolve_bill_source_aliases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill bill_source_aliases from likms billDetail billNo."
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    def run_bill_source_aliases() -> StageResult:
        result = resolve_bill_source_aliases(limit=args.limit)
        summary = asdict(result)
        dead_letters = tuple(
            DeadLetterDraft(
                source="bill_source_aliases",
                stage="resolve",
                item_key=ambiguity.source_bill_id,
                payload={
                    "source_bill_id": ambiguity.source_bill_id,
                    "bill_no": ambiguity.bill_no,
                    "canonical_bill_ids": ambiguity.canonical_bill_ids,
                    "relation_types": ambiguity.relation_types,
                    "n_relations": ambiguity.n_relations,
                },
                error="ambiguous canonical bill candidates",
            )
            for ambiguity in result.ambiguities
        ) + tuple(
            DeadLetterDraft(
                source="bill_source_aliases",
                stage="fetch",
                item_key=failure.source_bill_id,
                payload={
                    "source_bill_id": failure.source_bill_id,
                    "relation_types": failure.relation_types,
                    "n_relations": failure.n_relations,
                    "reason": failure.reason,
                },
                error=f"{failure.reason}: {failure.error}",
            )
            for failure in result.failures
        )
        return StageResult(summary=summary, dead_letters=dead_letters)

    run = run_staged_ingest(
        mode="backfill",
        stages=(BackfillStage("bill_source_aliases", run_bill_source_aliases),),
        run_metadata={"entrypoint": "backfill_bill_source_aliases", "issue": 82},
    )
    summary = run.stage_summaries["bill_source_aliases"]
    print(
        "Backfilled bill source aliases: "
        f"run_id={run.run_id} "
        f"status={run.status} "
        f"targets={summary['target_count']} "
        f"aliases={summary['alias_count']} "
        f"alias_relations={summary['alias_relation_count']} "
        f"accepted_gaps={summary['accepted_gap_count']} "
        f"accepted_gap_relations={summary['accepted_gap_relation_count']} "
        f"ambiguous={summary['ambiguous_count']} "
        f"failures={summary['failure_count']} "
        f"dead_letters={run.dead_letter_count}"
    )


if __name__ == "__main__":
    main()
