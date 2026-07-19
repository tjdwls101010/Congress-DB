# Hosted Postgres Migration Runbook

> **Historical note (2026-06-28):** The meeting/utterance domain (`meetings`, `meeting_bills`,
> `utterances`, view `bill_meeting_contexts`, function `search_utterances`) recorded below was
> later removed (migration `031_drop_meeting_minutes.sql`). Table counts and `search_utterances`
> examples here describe the pre-031 state, kept as a migration record.

> **Historical note (2026-06-10 pivot):** This runbook predates the no-SDK
> decision (see `docs/design/DECISIONS.md`). Mentions below of a "separate SDK
> repository" / "SDK-facing data" / "future SDK/app read traffic" are stale
> framing — there is no SDK; consumers (skills, AI agents, developers) read the
> hosted DB via **direct read-only SQL** as the `congress_ro` role (see
> `docs/design/DB-QUERY-GUIDE.md`). The migration facts in this file remain
> accurate; only the downstream-consumer framing changed.

This document records issue #63, the first Neon hosted Postgres migration.

As of 2026-06-06, the Neon restore and hosted smoke test are complete. The
hosted database is ready for the separate SDK repository to use.

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

- Hosted migration: complete.
- Neon organization: `Seongjin` (`org-rapid-heart-55745998`), plan `launch`.
- Neon project: `congress-db-staging` (`wispy-night-08362506`).
- Neon region: `aws-ap-southeast-1`.
- Hosted database: `congress`, role `congress_owner`, Postgres `17.10`.
- Hosted DB size after restore + smoke: `1224 MB`.
- Local pre-migration gate: `ready_for_human_review`.
- Accepted local backfill gate: `ingest_runs.id = 103`.
- Latest verified incremental baseline before the current dump: `ingest_runs.id = 371`.
- Latest auxiliary data backfills included in the current local DB:
  - `ingest_runs.id = 614` — missing bill summary backfill (#73).
  - `ingest_runs.id = 646` — bill_relations backfill (#72).
- Unresolved dead letters: `0`.
- Local readiness blockers: `0`.
- Local preflight on 2026-06-06:
  - `uv run python -m compileall congress_db scripts tests -q`: pass.
  - `uv run pytest -q`: `154 passed` after the CLI smoke fix (#80).
  - `make migration-readiness`: `ready_for_human_review`, blockers `0`.
- Current local dump artifact:
  `tmp/hosted-postgres-migration/congress-20260606-current-run646.dump` (`143M`).
  This file is not committed.
- The official local command is `uv run python -m scripts.ingest --mode backfill`
  or `make ingest-backfill`.
- The accepted backfill run proves the local 100% gate. The latest incremental
  run proves the current dump baseline. A strict empty-DB one-shot replay
  remains an optional final rehearsal before executing the remote restore.
- Any dump created before #54 is obsolete because it still contains the removed
  `session_groups` table.
- Any dump created before #72/#73 is stale for current SDK-facing data because
  it lacks `bill_relations` and the missing-summary backfill.

## Execution Result

- Restore source: `tmp/hosted-postgres-migration/congress-20260606-current-run646.dump`.
- Restore method: direct non-pooled Neon connection with `pg_restore --clean
  --if-exists --single-transaction --no-owner --no-privileges`.
- Restore result: success.
- `CREATE EXTENSION IF NOT EXISTS pg_trgm`: success (`pg_trgm` already existed after restore).
- `ANALYZE`: success for user tables. Neon-managed system catalog warnings are expected.
- Hosted S1-S7 sanity check: success.
- Hosted migration readiness: `ready_for_human_review`, blockers `0`.
- Hosted search smoke:
  - `search_bills('전세사기', 5)`: returned ranked bill rows.
  - `search_utterances('전세사기', 3)`: returned ranked utterance rows.
- Hosted incremental smoke:
  - Command: `uv run python -m scripts.ingest --mode incremental --force-meeting-id 56738`.
  - Result: `ingest_runs.id = 753`, mode `incremental`, status `success`, dead letters `0`.
  - Scope observed: members/bills/votes/meetings, full meeting_bills reconciliation, 8 touched utterance meetings, sanity, data completeness, migration readiness.

Hosted row counts after incremental smoke:

| Table | Rows |
|---|---:|
| `members` | 320 |
| `bills` | 18,361 |
| `bill_relations` | 3,715 |
| `bill_lead_proposers` | 17,559 |
| `bill_coproposers` | 206,299 |
| `votes` | 473,594 |
| `meetings` | 2,105 |
| `meeting_bills` | 40,345 |
| `utterances` | 1,378,280 |

The row counts differ from the dump baseline where the incremental smoke pulled
new source data and reconciled stale meeting-bill links. The hosted DB is the
current operational baseline after run `753`.

## Human Decisions Used For Execution

- Neon organization/project ownership and billing: PM upgraded the org to Launch.
- Neon region and plan: Launch in `aws-ap-southeast-1`.
- Direct, non-pooled Neon connection string was used for restore and hosted ingest.
- Pooled Neon connection string was retrieved for future SDK/app read traffic.
- First hosted DB name: `congress` in project `congress-db-staging`.
- Incremental sync initially runs from the local runner; no hosted cron/worker
  infrastructure was added in this slice.
- Optional destructive clean-DB rehearsal was skipped; the accepted local gate,
  restore verification, hosted sanity, and hosted incremental smoke were used as
  the acceptance chain.

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
current_run_id="646"
dump_path="tmp/hosted-postgres-migration/congress-$(date +%Y%m%d)-current-run${current_run_id}.dump"
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

This section is retained as the replay recipe. The initial hosted restore has
already been executed.

Use the Neon direct, non-pooled connection string for `pg_restore`. Neon pooled
connection strings use PgBouncer transaction pooling; they are for application
traffic, not schema/data restore tools.

```sh
dump_path="tmp/hosted-postgres-migration/congress-20260606-current-run646.dump"
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

The restore is not accepted until local and hosted Postgres produce matching
results for the dump baseline:

- Core table row counts:
  - `members`: 306
  - `bills`: 18,345
  - `bill_relations`: 3,715
  - `bill_lead_proposers`: 17,543
  - `bill_coproposers`: 206,138
  - `votes`: 473,594
  - `meetings`: 2,105
  - `meeting_bills`: 40,356
  - `utterances`: 1,378,071
- Unresolved dead letters: `0`.
- S1-S7 query outputs or checksums.
- Accepted data quality gaps from `docs/ops/DATA-COMPLETENESS.md` remain visible
  and unchanged unless a new source endpoint is intentionally added.

After the hosted incremental smoke, hosted row counts may legitimately move
ahead of the dump baseline because the source has newer data. See Execution
Result for the current hosted baseline.

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
- A full hosted incremental rehearsal completed successfully as run `753`.
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
