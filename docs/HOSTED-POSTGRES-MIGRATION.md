# Hosted Postgres Migration Runbook

This document starts issue #12. It deliberately stops before executing the
remote migration because project creation, billing, region, credentials, and the
first hosted environment are human-owned decisions.

As of 2026-06-04, the project is intentionally paused at the pre-restore
boundary. The local database has been verified and dumped; the Neon restore and
hosted smoke test wait for PM authorization and a direct, non-pooled hosted
connection string.

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
- Accepted local backfill gate: `ingest_runs.id = 103`.
- Latest verified incremental baseline: `ingest_runs.id = 190`.
- Unresolved dead letters: `0`.
- Local readiness blockers: `0`.
- Local preflight on 2026-06-04:
  - `uv run python -m compileall congress_db scripts tests -q`: pass.
  - `uv run pytest -q`: `134 passed`.
  - `make migration-readiness`: `ready_for_human_review`, blockers `0`.
- Current local dump artifact:
  `tmp/hosted-postgres-migration/congress-20260604-run190.dump` (`144M`).
  This file is not committed.
- The official local command is `uv run python -m scripts.ingest --mode backfill`
  or `make ingest-backfill`.
- The accepted backfill run proves the local 100% gate. The latest incremental
  run proves the current dump baseline. A strict empty-DB one-shot replay
  remains an optional final rehearsal before executing the remote restore.
- Any dump created before #54 is obsolete because it still contains the removed
  `session_groups` table. Recreate the dump after local schema migration,
  sanity check, and migration readiness pass.

## Human Decisions Before Execution

- Neon organization/project ownership and billing.
- Neon region and plan. Recommended: Launch in `aws-ap-southeast-1`.
- Direct, non-pooled Neon connection string for restore, exposed locally as
  `NEON_DATABASE_URL_UNPOOLED` or `HOSTED_DATABASE_URL`.
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
uv run python -m compileall congress_db scripts tests -q
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
baseline_run_id="190"
dump_path="tmp/hosted-postgres-migration/congress-$(date +%Y%m%d)-run${baseline_run_id}.dump"
docker compose exec -T db pg_dump \
  -U "${POSTGRES_USER:-congress}" \
  -d "${POSTGRES_DB:-congress}" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --no-subscriptions \
  --verbose \
  > "$dump_path"
```

Do not commit the dump. It is an operational artifact.

## Restore

Do not run this section until the PM authorizes the hosted migration execution
and provides the direct, non-pooled Neon connection string.

Use the Neon direct, non-pooled connection string for `pg_restore`. Neon pooled
connection strings use PgBouncer transaction pooling; they are for application
traffic, not schema/data restore tools.

```sh
dump_path="tmp/hosted-postgres-migration/congress-20260604-run190.dump"
export HOSTED_DATABASE_URL="$NEON_DATABASE_URL_UNPOOLED"

pg_restore \
  --dbname "$HOSTED_DATABASE_URL" \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  --single-transaction \
  --verbose \
  "$dump_path"
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
  - `bills`: 18,345
  - `bill_lead_proposers`: 17,543
  - `bill_coproposers`: 206,138
  - `votes`: 473,594
  - `meetings`: 2,105
  - `meeting_bills`: 40,356
  - `utterances`: 1,378,071
- Unresolved dead letters: `0`.
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

- Current utterance repair is verified by the 2026-05-31 recovery drill.
- Bills/votes/meeting-bill links still need one full hosted incremental rehearsal
  before calling the hosted DB production-ready.
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
