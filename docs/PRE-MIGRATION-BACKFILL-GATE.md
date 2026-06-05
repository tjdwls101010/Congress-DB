# Pre-migration Local Backfill Gate

This is the operating contract for issue #45. Hosted Postgres migration (#12) must wait until
this gate is complete.

## Goal

Prove that the initial ~2 years of 22대 data can be loaded, verified, and rerun
locally before any `pg_dump` / `pg_restore` migration to hosted Postgres.

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
7. Only then mark the gate complete and proceed to hosted Postgres migration planning.

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
- S1-S7 sanity scenarios are generated and reviewable.
- Data-completeness gaps are fixed, expected, or accepted with evidence.
- Idempotency rerun does not duplicate members, bills, votes, meetings,
  meeting-bill links, or utterances.
- Final artifacts are refreshed from the accepted run.

## Accepted Local Run

- Accepted run: `ingest_runs.id = 103`
- Status: `success`
- Finished at: `2026-05-30 00:12:08 UTC`
- Dead letters: `0`
- Migration readiness: `ready_for_human_review`
- Core row counts:
  - `members`: 306
  - `bills`: 18,345
  - `bill_lead_proposers`: 17,543
  - `bill_coproposers`: 206,138
  - `votes`: 473,594
  - `meetings`: 2,105
  - `meeting_bills`: 40,356
  - `utterances`: 1,378,071

## Confidence And Remaining Risk

- High confidence: the current local database contains the target backfill data,
  has no unresolved dead letters and generates all S1-S7 review paths.
- High confidence: the known operational failures from the monitored runs were
  addressed in code: OpenAPI retry storms, retry-aware worker selection, failed
  vote row retry, stdout/stderr breakage, and late-stage rerun reuse.
- Accepted source gaps remain visible rather than hidden: 20 referenced member
  stubs have no profile party, 1,028 vote-created bill rows lack source proposal
  date and summary, 40 non-vote bill rows lack source summary, and 9
  member-titled utterances have no safe member FK. These affect profile
  completeness or search recall, not relational integrity.
- Remaining uncertainty: run `103` reused healthy completed expensive stages
  from earlier monitored runs. It proves the current local data state and the
  resumed official path, but it is not strict proof that the current code can
  populate an empty database in one uninterrupted run.
- If strict audit confidence is required before migration execution, run one
  destructive clean-DB rehearsal from a saved dump/snapshot and accept only if
  the final row counts, S1-S7 outputs, dead letters, and readiness report match
  this gate.

## Recovery Drill

- Date: `2026-05-31`
- Method: created a throwaway Postgres database from the accepted local DB,
  deleted recent utterance data only inside that clone, then reran
  the relevant ingest modules against the same meeting ids twice.
- Target meetings: `56738`, `56737`, `56731` (latest dated meetings with
  utterances).
- Deleted and restored:
  - `utterances`: 16 + 109 + 439 = 564 rows
- Result after first repair run:
  - scraped meetings: 3
  - scrape errors: 0
  - restored utterance counts matched the pre-delete counts for all 3 meetings
  - duplicate `(meeting_id, sequence)` rows: 0
- Result after second same-target rerun:
  - utterance count remained 564
  - duplicate `(meeting_id, sequence)` rows remained 0
- Scope boundary: this verified the recent meeting minutes, utterance, and
  repair path without touching the accepted local DB. It did not
  run the full official `incremental` command because current bills/votes
  incremental stages still perform broad source scans; testing those through the
  official Interface should be done as a separate hosted-DB migration rehearsal
  or after adding narrower windowed repair controls.

## Findings From The Monitored Run

- OpenAPI summary calls are the sensitive external bottleneck. A 200-worker run
  completed the benchmark sample without final errors, but produced a retry
  storm and lower real throughput. Benchmark selection now records retry rate
  and rejects retry-heavy worker counts instead of treating eventual success as
  healthy.
- The benchmark sample for official OpenAPI backfill is now 1,000 representative
  items across the target universe. HTML minutes scraping remains at 300
  representative items because it is source-heavier and has a retry-rate guard.
- Failed late-stage reruns must not refetch already completed expensive stages.
  The official backfill now reuses healthy `members`, `bills`, `votes`, and
  `meetings` stage summaries from previous failed backfill runs.
- Terminal output is telemetry, not data integrity. Broken stdout/stderr no
  longer fails a run by itself.
- Migration readiness must be generated after the backfill run is marked
  complete. Generating it as an in-run stage observes the current run as
  `running` and produces a false blocker.

## Output Artifacts

- `docs/MIGRATION-READINESS.md`
- `docs/SANITY-CHECK.md`
- `docs/DATA-COMPLETENESS.md`
- `docs/MINUTES-WEB-COVERAGE.md`
- Relevant benchmark docs when worker selection or performance changes.
- Issue #45 comments or PR body entries summarizing each abnormal finding and fix.
