# Supabase Migration Runbook

This document starts issue #12. It deliberately stops before executing the
remote migration because project creation, billing, region, credentials, and RLS
policy are human-owned decisions.

## Current Status

- Local pre-migration gate: `ready_for_human_review`.
- Accepted local backfill run: `ingest_runs.id = 103`.
- Unresolved dead letters: `0`.
- Local readiness blockers: `0`.
- The official local command is `uv run python -m scripts.ingest --mode backfill`
  or `make ingest-backfill`.
- The accepted run proves the current local data state and resumed official
  path. A strict empty-DB one-shot replay remains an optional final rehearsal
  before executing the remote restore.

## Human Decisions Before Execution

- Supabase project region and plan.
- Whether the project needs IPv4 add-on or can use IPv6/direct connection for
  native Postgres tools.
- RLS policy for the first public data release:
  - RLS off on public congressional-data tables until a direct client-facing API
    exists.
  - RLS on with public read policies before exposing tables through Supabase
    client keys.
- Whether incremental sync runs from a local/CI worker first, or moves to
  Supabase Edge Functions / scheduled jobs in a later slice.
- Whether to run the optional destructive clean-DB rehearsal before remote
  migration execution.

## Local Preflight

Run these immediately before taking the dump:

```sh
uv run pytest -q
make migration-readiness
git status --short --branch
```

Expected readiness:

- `Recommendation: ready_for_human_review`
- `Blockers: None`
- `dead_letters = 0`
- S1-S7 sanity signal available
- data completeness signal available

## Dump

Create a portable dump without local ownership or privilege metadata:

```sh
mkdir -p tmp/supabase-migration
docker compose exec -T db pg_dump \
  -U "${POSTGRES_USER:-congress}" \
  -d "${POSTGRES_DB:-congress}" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --no-subscriptions \
  --verbose \
  > tmp/supabase-migration/congress.dump
```

Do not commit the dump. It is an operational artifact.

## Restore

Use the Supabase direct connection string when the machine supports IPv6. If
that is not available, use the Supavisor session-mode pooler. Do not use the
transaction-mode pooler for `pg_restore`.

```sh
pg_restore \
  --dbname "$SUPABASE_DB_URL" \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  --single-transaction \
  --verbose \
  tmp/supabase-migration/congress.dump
```

After restore:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
ANALYZE;
```

The local schema already includes `CREATE EXTENSION IF NOT EXISTS pg_trgm` in
`db/migrations/001_search_indexes.sql`; the explicit check makes the restore
failure mode obvious if extension permissions differ.

## Verification

The migration is not accepted until local and Supabase produce matching results
for:

- Core table row counts:
  - `members`: 306
  - `bills`: 18,333
  - `bill_lead_proposers`: 17,531
  - `bill_coproposers`: 206,014
  - `votes`: 473,594
  - `meetings`: 2,103
  - `meeting_bills`: 40,353
  - `utterances`: 1,373,867
  - `session_groups`: 30,663
- Unresolved dead letters: `0`.
- Session group integrity metrics: all `0`.
- S1-S7 query outputs or checksums.
- Accepted data quality gaps from `docs/DATA-COMPLETENESS.md` remain visible and
  unchanged unless a new source endpoint is intentionally added.

Issue #12 should add or reuse an agent-runnable compare script so the local and
remote checks are not manual copy/paste.

## Incremental Sync Smoke Test

After restore, run the official ingest command against Supabase with a narrow
forced target or the normal incremental mode:

```sh
DATABASE_URL="$SUPABASE_DB_URL" uv run python -m scripts.ingest --mode incremental
```

Acceptance:

- The command creates an `incremental` `ingest_runs` row in Supabase.
- Upserts do not duplicate core rows.
- Any source failure is either retried/resolved or captured in `dead_letters`.
- `make migration-readiness` against the Supabase connection remains
  review-ready after the incremental run.

## References

- Supabase Postgres migration guide:
  https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres
- Supabase database connection guidance:
  https://supabase.com/docs/guides/database/connecting-to-postgres/serverless-drivers
- Supabase Postgres extensions guidance:
  https://supabase.com/docs/guides/database/extensions
- Supabase database migration workflow:
  https://supabase.com/docs/guides/deployment/database-migrations
