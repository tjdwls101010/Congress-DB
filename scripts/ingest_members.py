#!/usr/bin/env python3
"""members 적재 CLI."""

from __future__ import annotations

from congress_db.ingest.ingest_members import ingest_members


def main() -> None:
    result = ingest_members()
    age = (
        next(iter(result.age_param_used.items()))
        if result.age_param_used
        else ("age", "none")
    )
    print(
        "Ingested members: "
        f"fetched={result.fetched_count}/{result.total_count} "
        f"upserted={result.upserted_count} "
        f"{age[0]}={age[1]}"
    )


if __name__ == "__main__":
    main()
