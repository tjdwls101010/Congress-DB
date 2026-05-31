# Unify backfill and incremental ingest

Initial 22대 backfill and later incremental sync use the same ingest modules; only the execution mode and source window differ. Incremental sync uses source-specific cursors with a 30-day overlap, records every run in `ingest_runs`, preserves persistent failures in `dead_letters`, and initially runs from a local or separate runner that upserts directly into hosted Postgres.
