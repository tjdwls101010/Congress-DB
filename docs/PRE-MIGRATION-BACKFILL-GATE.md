# Pre-migration Local Backfill Gate

This is the operating contract for issue #45. Supabase migration (#12) must wait until
this gate is complete.

## Goal

Prove that the initial ~2 years of 22대 data can be loaded, verified, and rerun
locally before any `pg_dump` / `pg_restore` migration to Supabase.

The target is not "the command exits once." The target is a repeatable local
backfill process whose slow stages, retries, skipped targets, dead letters, and
data-quality gaps are understood and either fixed or explicitly accepted.

## Run Loop

1. Start from a clean local Postgres DB.
2. Run the official ingest command for the 100% local backfill.
3. Monitor CLI progress continuously enough to notice abnormal stage duration,
   stalled worker progress, retry loops, or unexpectedly low row counts.
4. Inspect `ingest_runs`, `dead_letters`, generated reports, and row counts after
   each run.
5. If any signal is abnormal, improve the ingest logic or classification, then
   rerun the affected path.
6. After a clean full load, rerun the official command as an idempotency check.
7. Only then mark the gate complete and proceed to Supabase migration planning.

## Monitoring Signals

- CLI stage progress and summaries.
- Stage duration compared with benchmark documents.
- Worker count selected and retry/error rate by stage.
- `ingest_runs.status`, `summary`, `error`, and per-stage summaries.
- `dead_letters` grouped by source, stage, status, and item key.
- Row counts for all core tables and junction tables.
- `docs/MINUTES-WEB-COVERAGE.md` coverage gap.
- `docs/SANITY-CHECK.md` S1-S7 query outputs.
- `docs/DATA-COMPLETENESS.md` unresolved or accepted gaps.
- `docs/SESSION-GROUPS-CALIBRATION.md` integrity section.
- `docs/MIGRATION-READINESS.md` blocker list.

## Failure Handling

- A slow stage is a diagnosis trigger, not just something to wait out. Compare it
  with prior benchmarks, then tune worker selection, query shape, retry policy, or
  target selection if the slowdown is not explained.
- Unresolved dead letters block migration.
- Known source defects may be ignored only when the item, source behavior, and
  reason for not recovering through PDF/HWP fallback are documented.
- `degraded_success` is not accepted for migration unless every degraded item is
  resolved or explicitly classified as an accepted source defect.
- A successful command exit is not enough if row counts, skipped targets, or
  generated reports disagree with the expected universe.

## Pass Criteria

- Clean local DB can be populated by the official full backfill path.
- Final accepted run has no unresolved dead letters.
- Web minutes coverage has no unexplained gap.
- Session group integrity errors are 0.
- S1-S7 sanity scenarios are generated and reviewable.
- Data-completeness gaps are fixed, expected, or accepted with evidence.
- Idempotency rerun does not duplicate members, bills, votes, meetings,
  meeting-bill links, utterances, or session groups.
- Final artifacts are refreshed from the accepted run.

## Output Artifacts

- `docs/MIGRATION-READINESS.md`
- `docs/SANITY-CHECK.md`
- `docs/DATA-COMPLETENESS.md`
- `docs/MINUTES-WEB-COVERAGE.md`
- `docs/SESSION-GROUPS-CALIBRATION.md`
- Relevant benchmark docs when worker selection or performance changes.
- Issue #45 comments or PR body entries summarizing each abnormal finding and fix.
