# Decisions

Newest first. Each entry: `## YYYY-MM-DD — short title`, then 1-3 sentences
(context + decision + why).

## 2026-06-04 — Incremental meeting_bills skips linked bills and preserves existing links

After #46, incremental meetings cost was dominated by re-querying `VCONFBILLCONFLIST`
for already-linked bills. Incremental mode now fetches meeting-bill rows only for
missing/unlinked bills and bills on touched or forced meetings; it upserts new pairs
without deleting existing `meeting_bills`, leaving stale-link deletion to full
reconciliation/backfill. This trades rare stale-link cleanup latency for avoiding
false deletion when a skipped bill still owns an existing link.

## 2026-06-04 — Remove session_groups; minutes retrieval = utterance keyword + neighbor-reading

Following the agentic + ranked-keyword search decision, the Q&A semantic unit
(`session_groups`, 30,755 rows) is removed, not merely demoted. Rationale:
`utterances.speaker_mona_cd` already answers "who said what"; session_groups uniquely
added only questioner↔respondent pairing + Q&A block boundaries, both re-derivable on the
fly by an agentic harness; its accuracy was never measured (#50), coverage is uneven
(본회의·소위 none; 상임위 69%, 국정조사 65%, only 국정감사 99%); and it carried a
detection/eval subsystem plus an incremental regroup stage. Minutes content is untouched —
all 1.38M utterances remain; only the derived segmentation layer drops, and the detection
code stays in git if ever needed. Removal slice: #54; #50 closed as obsolete.

## 2026-06-04 — Search strategy: agentic + ranked keyword, defer vector embeddings

The search layer (roadmap steps 2-4) will use agentic keyword search — Claude issues
multiple domain-informed query variants, follows structural JOINs
(bill→votes→meetings→utterances), and iterates — over a keyword layer upgraded from
substring-only to relevance-ranked + snippets (Postgres-native `similarity()`/snippet, no
new infra). Vector/embedding semantic search is deferred, not adopted: this terminological,
citation-critical, low-QPS legislative domain lets Claude's own vocabulary + agentic
iteration recover most semantic recall, while embeddings carry ongoing maintenance (Korean
model hosting, weekly re-embedding of new utterances, model-version re-embeds, pgvector
storage/cost). Deferring is low-risk because pgvector is additive later (Neon supports it;
source text already stored) — no DB rebuild; revisit only if a measured recall failure
proves agentic+ranked-keyword insufficient. The `legislative-copilot` prototype already
validated keyword+agentic without vectors. DB implication: add relevance-ranking support
when the SDK slice begins.

## 2026-06-04 — Four-project roadmap: this repo is the 국회 DB only

The legislative-design harness needs three sources — 국회 (proposed/discussed/voted
bills, this repo), 법제처 (in-force statutes·decrees·official interpretations·precedents),
and WebSearch (social context) — so the work is split into four sequential, independent
projects: (1) 국회 data DB = this repo → (2) 국회 SDK → (3) 법제처 SDK → (4) harness skill,
keeping each project's scope bounded. Consequently statute/decree/interpretation/precedent
text is explicitly out of this repo (it belongs to the 법제처 SDK), and the prior
`legislative-copilot` prototype is reference-only and will be rebuilt. See CONTEXT.md
"프로젝트 경계 / 로드맵".

## 2026-06-04 — Incremental sync re-scans cheap lists, skips immutable items (drops the 30-day window)

The documented "source-specific cursor + 30-day overlap window" incremental design
(ADR-0006, PRD #37/#39, CONTEXT 증분 동기화) was never wired in: `incremental_plan.py` was
dead code and the live path full-refetched everything every run — re-pulling ~18k immutable
bill summaries and ~1,600 bills' vote rows, and re-running worker benchmarks. Decision:
incremental re-scans the cheap list endpoints in full each run (so late edits to old
records, e.g. a year-old bill's `proc_result` changing, are always caught) and upserts all,
but skips per-item fetches for items already present (bill summaries and vote rows are
immutable once set) and runs benchmarks only at first calibration; the date-window model is
dropped because legislative records are edited late and a 30-day window misses them.
Issue #46 removes the unused planner and verifies the behavior with public-interface tests
plus one real-source dry run. Supersedes the windowing aspect of ADR-0006.

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
