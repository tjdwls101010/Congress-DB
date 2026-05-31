# Hosted Postgres Migration Runbook

This document starts issue #12. It deliberately stops before executing the
remote migration because project creation, billing, region, credentials, and the
first hosted environment are human-owned decisions.

## Provider Decision

- Selected target for the first hosted database: Neon Launch.
- Reason: this project currently needs hosted Postgres only. Auth, Storage,
  Realtime, direct client SDK access, and platform-managed Edge Functions are
  not first-order requirements.
- Supabase remains a valid alternative if the product later needs Auth/RLS/API
  platform features in the same vendor surface.
- Recommended Neon region: `aws-ap-southeast-1` (Singapore), the closest
  currently documented Neon AWS region for a Korea-based project.
- Recommended initial compute: min `0.25 CU`, max `2 CU`, scale-to-zero enabled
  for staging. Disable scale-to-zero later only if cold starts affect a public
  product path.

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

- Neon organization/project ownership and billing.
- Neon region and plan. Recommended: Launch in `aws-ap-southeast-1`.
- Whether the first hosted DB is named `congress_staging`, `congress`, or another
  environment-specific name.
- Whether the staging compute may scale to zero. Recommended: yes for staging.
- Whether incremental sync runs from a local/CI worker first. Recommended: yes;
  do not add hosted cron/worker infrastructure until the first remote restore
  and smoke test pass.
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
mkdir -p tmp/hosted-postgres-migration
docker compose exec -T db pg_dump \
  -U "${POSTGRES_USER:-congress}" \
  -d "${POSTGRES_DB:-congress}" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --no-subscriptions \
  --verbose \
  > tmp/hosted-postgres-migration/congress.dump
```

Do not commit the dump. It is an operational artifact.

## Restore

Use the Neon direct, non-pooled connection string for `pg_restore`. Neon pooled
connection strings use PgBouncer transaction pooling; they are for application
traffic, not schema/data restore tools.

```sh
export HOSTED_DATABASE_URL="$NEON_DATABASE_URL_UNPOOLED"

pg_restore \
  --dbname "$HOSTED_DATABASE_URL" \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  --single-transaction \
  --verbose \
  tmp/hosted-postgres-migration/congress.dump
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

The migration is not accepted until local and hosted Postgres produce matching results
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

After restore, run the official ingest command against hosted Postgres. Prefer a
narrow forced meeting target first, then a normal incremental rehearsal:

```sh
DATABASE_URL="$HOSTED_DATABASE_URL" \
  uv run python -m scripts.ingest --mode incremental --force-meeting-id 56738
```

Acceptance:

- The command creates an `incremental` `ingest_runs` row in hosted Postgres.
- Upserts do not duplicate core rows.
- Any source failure is either retried/resolved or captured in `dead_letters`.
- `make migration-readiness` against the hosted connection remains
  review-ready after the incremental run.

## Follow-up Before Production Operation

- Current utterance/session-group repair is verified by the 2026-05-31 recovery
  drill.
- Bills/votes still need either one full hosted incremental rehearsal or narrower
  windowed repair controls before calling the hosted DB production-ready.
- App/serverless runtimes should use the Neon pooled connection string. Native
  migration/backup/restore tools should use the direct non-pooled connection.

## References

- Neon pricing:
  https://neon.com/pricing
- Neon regions:
  https://neon.com/docs/conceptual-guides/regions
- Neon connection pooling:
  https://neon.com/docs/connect/connection-pooling
- Neon Postgres extensions:
  https://neon.com/docs/extensions/extensions-intro
