# Decisions

Newest first. Each entry: `## YYYY-MM-DD — short title`, then 1-3 sentences
(context + decision + why).

## 2026-05-31 — Target Neon for the first hosted Postgres migration

The project currently needs hosted Postgres, not Auth/Storage/Realtime/Edge
platform features. The first remote target is Neon Launch, with a staging restore
before any production claim; Supabase stays as an alternative if product
requirements later need its broader platform surface.

## 2026-05-30 — Separate local data acceptance from strict clean replay proof

The accepted local database is ready for hosted Postgres human review because
run `103` finished with `success`, `0` dead letters, passing S1-S7 checks, and
`ready_for_human_review`. This does not claim a strict empty-DB one-shot replay
with the current code; that destructive rehearsal remains optional before
migration execution, not a blocker to migration planning.

## 2026-05-30 — Migration readiness runs after backfill completion

`migration_readiness` reads the latest backfill run, so running it as a stage
inside the same backfill sees that run as `running`. The official ingest command
now refreshes readiness after the backfill status is finalized.

## 2026-05-30 — Reuse completed backfill stages on rerun

Late-stage failures should not force expensive OpenAPI and meeting fetch stages
to run again. The official backfill now reuses healthy `members`, `bills`,
`votes`, and `meetings` summaries from previous failed backfill runs and records
the source run id in the new run summary.

## 2026-05-30 — Retry rate is a worker-selection signal

For external sources, eventual success with heavy retries is not stable enough
for the migration gate. OpenAPI and minutes benchmarks treat retry storms as a
worker rejection signal, not just as noisy logs.

## 2026-05-30 — Full session-group relink rebuilds the link index

The local full backfill relinks hundreds of thousands of utterances to
`session_groups`; maintaining the partial `session_group_id` index during that
write caused excessive IO. Large relinks temporarily drop and recreate that
index inside the transaction.
