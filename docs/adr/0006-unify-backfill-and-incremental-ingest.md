# Unify backfill and incremental ingest

> **Superseded in part — 2026-06-04 (see DECISIONS 2026-06-04 / issue #46).** The "same modules, different mode" principle stands, but the "source-specific cursor + 30-day overlap window" mechanism is dropped: incremental re-scans cheap list endpoints in full (to catch late edits to old records) and skips immutable per-item fetches (bill summaries, vote rows). The paragraph below describes the original, now-superseded windowing design.

Initial 22대 backfill and later incremental sync use the same ingest modules; only the execution mode and source window differ. Incremental sync uses source-specific cursors with a 30-day overlap, records every run in `ingest_runs`, preserves persistent failures in `dead_letters`, and initially runs from a local or separate runner that upserts directly into hosted Postgres.
