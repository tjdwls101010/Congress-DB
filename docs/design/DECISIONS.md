# Decisions

Newest first. Each entry: `## YYYY-MM-DD — short title`, then 1-3 sentences
(context + decision + why).

## 2026-06-11 — bill_final_outcomes stores PROM_LAW_NM, not a numeric law_id

Issue #86 planned a `law_id` column as the 법제처 bridge, but a live ALLBILL check shows the endpoint
returns no clean numeric 법령ID — only `PROM_LAW_NM` (the promulgated law name) and a `LINK_URL` that
merely points back to the likms bill page (`billDetail.do?billId=<BILL_ID>`). Decision: store
`prom_law_nm` (promulgated law name) instead of `law_id`; the law name is the actual key 법제처 (the
future statute SDK) is queried by, so the bridge intent is preserved while staying honest about what
the source provides. Reversible — a numeric 법령ID column can be added later if a source supplies one.

## 2026-06-10 — No 국회 SDK; the future skill queries Neon directly via SQL over a schema reference

The planned 국회 SDK (roadmap step 2) was a fixed query surface — brittle (one wrong or
missing method blocks the consumer) and an ongoing maintenance burden for a solo PM, while real
legislative-analysis questions are open-ended. Decision: drop the SDK; the future 입법전문가 스킬
connects to Neon and runs read-only SQL directly, guided by this DB's own schema/usage
documentation, because Claude is strong at SQL and the target skill is a human-in-the-loop
deliberative copilot (the user reviews every result, bounding ad-hoc-SQL risk). Consequences:
(1) a least-privilege **read-only DB role is now mandatory** — an LLM writing SQL must not hold
owner rights; (2) the DB must be **self-sufficient** because there is no SDK layer to paper over
gaps, which elevates the source-fact backfills below; (3) `docs/CONGRESS-SDK-CODEX-BRIEF.md` is
obsolete; (4) roadmap step 2 changes from "국회 SDK" to "DB reference + direct SQL". Reversible —
an SDK can wrap the same schema later if direct SQL proves insufficient.

## 2026-06-10 — BILL_NO is the stable cross-source key; BILL_ID can diverge per source

A 4-agent analysis + adversarial verification (transcript 2026-06-10) found that the 130 "missing"
대안 `bill_relations.alternative_bill_id`s compress to **15 distinct source ids, and 15/15 already
exist in `bills` under the same `BILL_NO` but a different `BILL_ID`** — e.g. relation target
`PRC_D2L5…` is, per likms/ALLBILL, `BILL_NO 2212725`, which `bills` stores as `PRC_V2S5…`. likms
and ALLBILL key by `BILL_NO`. Decision: keep `bills.bill_id` as PK, but treat `BILL_NO` as the
stable cross-source identity and add `bill_source_aliases(source, source_bill_id, bill_no,
canonical_bill_id)` to reconcile divergent source `BILL_ID`s to the canonical row. This
operationalizes (does not reverse) the 2026-06-06 "alternative_bill_id is a source key, not an FK"
decision, and still forbids synthetic `bills` rows.

## 2026-06-10 — Add bill_final_outcomes (ALLBILL 공포 bridge) keyed by BILL_NO, not columns on bills

`bills.law_proc_dt` is a 법사위 처리일, not 공포일 (570 present, all earlier than `proc_dt`;
promulgation absent entirely), and 720 distinct passed alternatives have it NULL — so "그 대안은
결국 통과·공포됐나?" dead-ends. A live ALLBILL check returns `PROM_DT` (공포일), `PROM_NO`
(공포번호), `GVRN_TRSF_DT` (정부이송일), `PPSL_DT` (제안일) keyed by `BILL_NO`. Decision: add a
separate `bill_final_outcomes(bill_no PK, plenary_dt, govt_transfer_dt, promulgation_dt, prom_no,
law_id, source)` ingested from ALLBILL rather than NULL-heavy columns on `bills` — keying by
`BILL_NO` reaches the BILL_ID-alias'd and missing alternatives that bills-columns cannot,
simultaneously backfills 대안 `propose_dt` via `PPSL_DT`, and provides the 국회-stage bridge key
(`law_id`) toward the later 법제처 layer (statute text stays out of scope).

## 2026-06-06 — bill_relations alternative id is a source key, not a required bills FK

During the #72 backfill, `selRefBillId` resolved all 3,715 target original bills, but 169 pointed to
ids not present in our `bills` table: 130 committee alternatives that likms detail pages expose but
our bill-list ingest missed, plus all 39 수정안 ids whose bill detail pages do not exist. Creating
synthetic `bills` rows would pollute the Bill entity, and enforcing an FK would discard authoritative
relationship facts, so `bill_relations.absorbed_bill_id` remains an FK while `alternative_bill_id`
is stored as the authoritative likms source key; it joins to `bills` when a row exists and can be
enriched later.

## 2026-06-06 — bill_relations source: scrape likms `selRefBillId`, not the OpenAPI

The 국회 OpenAPI exposes no 원안↔대안 relationship field — checked 발의법률안 (24 fields), ALLBILL
(full processing timeline soup-to-nuts, but no link), the dedicated 위원회안·대안 API
(`nxtkyptyaolzcbfwl`), and BPMBILLSUMMARY (returns policy text, not the absorbed-bill list). The
authoritative link lives only in 의안정보시스템 (likms) `billDetail.do` as a hidden
`<input id="selRefBillId">` pointing 원안→흡수 대안, in static HTML (sample 10/10 exact). So
`bill_relations` is populated by scraping selRefBillId (~100%, authoritative) rather than a
name+shared-committee-meeting heuristic (~80%, inferred) — precision matters more than effort for a
proposal-basis fact, and the scrape reuses the existing minutes-scraper pattern (no new
dependency). Scope: 대안반영폐기 (3,676) + 수정안반영폐기 (39), distinguished by `relation_type`.
Aside: ALLBILL carries 공포·본회의 dates absent from our `bills` table — future enrichment, out of
scope for this slice.

## 2026-06-06 — Track incumbency via a roster-derived boolean; never delete departed members

Departed legislators (사퇴/의원직 상실 등) are never removed — FK ON DELETE RESTRICT already
blocks deleting any member with votes/utterances, and member sync upserts rather than deletes.
The only missing piece was knowing who currently serves: add `members.is_incumbent` (BOOLEAN),
set TRUE for members present in the latest 인적사항 roster sync and FALSE otherwise, refreshed
automatically every sync (not hand-maintained) — consistent with the "derive point-in-time
facts from the source" pattern (cf. `votes.poly_nm_at_vote`). Chosen over a status enum +
end-date (no reliable source for reason/exact date → mostly NULL = over-design). Members who
depart after our sync window keep their last roster profile frozen; only the 20 pre-sync
departures stay profile-NULL (separate backlog). Floor-only vote scope reaffirmed (committee
votes are absent from the OpenAPI, not merely unimportant).

## 2026-06-05 — Foundation diagnosis: clean facts, not yet a proposal basis

A 9-agent diagnosis (transcript 2026-06-05) judged the DB a trustworthy SOURCE OF FACTS
but not yet a trustworthy BASIS FOR PROPOSALS — the threads a bill proposal must follow
dead-end. Two are now in scope to close in this repo (PRD #50-53): (1) bill-to-bill 대안
관계 + passed-대안 summary backfill, (2) speaker_role normalization + executive-branch
utterance attribution. Deferred to backlog: filling 20 profile-less member stubs, raising
상임위 meeting_bills coverage. Indicative fit scores: data/domain 52, architecture 42.

## 2026-06-05 — 국회 SDK stays a separate repo (reaffirmed after reconsidering in-place merge)

Considered renaming this repo to congress-sdk and growing the API/SDK in place. Rejected:
write-path (ingestion) and read-path (SDK) couple only through the Neon schema reached by
one DATABASE_URL, so the SDK needs the database, not this repo's code, scraping stack, or
batch lifecycle; their consumers and release cadences differ; and the downstream 법제처 SDK
+ harness (also separate repos) want 국회 SDK as an installable dependency. Reaffirms the
roadmap (CONTEXT 프로젝트 경계). Reversible (separate↔mono via history-preserving subtree
split/merge) if two-repo overhead proves too heavy for a solo PM.

## 2026-06-05 — Hybrid sequencing: stabilize foundation here, then SDK slices parallel to data fixes

Work order in THIS repo: M0 (doc-truth fixes, docs structure cleanup) → M1 (ADR-0008 schema
cleanup, search-ranking migration, Neon migration, hosting-continuity hardening) → open the
congress-sdk repo against the stabilized schema and build thin vertical slices, closing the
two M2 data threads (대안 관계, speaker_role) in parallel. Chosen over "all data first"
(delays end-to-end feedback) and "SDK first" (builds on knowingly-slanted data), per the
vertical-slice philosophy.

## 2026-06-05 — Accept the leaked (free) API key in git; remove legacy tree only for tidiness

The National Assembly OpenAPI key committed at .Seongjin/legacy_congress/.env is free and
trivially reissued, so the leak carries no billing risk; history is NOT scrubbed (PM
decision). The only residual is per-key rate-limit abuse, accepted. Removing
.Seongjin/legacy_congress/ (dead SQLite-era scripts + a 472KB binary) is therefore an
optional tidiness slice, not a security action. Executed in #58 after inline-preserving
the used endpoint inf_ids in `congress_db/core/endpoints.py`.

## 2026-06-05 — Consolidate per-file ADRs into this log; split docs into design/ vs ops/

Executed in slice #57. The previous per-file ADRs predated the single-decision-log decision
and were absorbed into this log with decision content preserved, then removed. docs/ now
splits into design/ (hand-edited: PRD, IA, ERD, DECISIONS, migration runbook) vs ops/
(code-generated reports: sanity, completeness, readiness, benchmarks, DOM validation);
generators write to docs/ops/ and that dir is gitignored.

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

## 2026-05-29 — Single ingest entrypoint for PM and operator runs

PMs and operators should run one ingest command, not manually compose member, bill,
vote, meeting, utterance, and session-group stages. The command decides whether the
run is initial backfill or incremental sync, retries unresolved dead letters first,
avoids duplicate rows through upserts and scoped recalculation, and records the
decision path in `ingest_runs` so later sessions can audit what happened. Absorbed
from ADR-0009.

## 2026-05-29 — Keep core schema search-oriented

Congress-DB is the foundation for future search APIs/SDKs, not a full archive of
every upstream field. Source links, source-tracking fields, and `agenda_items` are
kept out of the core schema before hosted Postgres migration; official meeting
agenda text may be used transiently to derive `meeting_bills`, while policy topics
and positions will be modeled later as a separate evidence-backed semantic layer.
Absorbed from ADR-0008.

## 2026-05-29 — Web minutes list is the canonical meeting universe

The public OpenAPI meeting endpoints and the `record.assembly.go.kr/assembly/mnts/total/22.do`
web listing do not expose the same 22대 minutes universe, while utterances are parsed
only from HTML viewer pages. The web listing is the canonical meeting universe;
OpenAPI meeting endpoints only enrich metadata and law-bill links by matching
`mnts_id`, and PDF/HWP stay out of utterance extraction. Absorbed from ADR-0007.

## 2026-05-27 — Backfill and incremental ingest share modules

Initial 22대 backfill and later incremental sync use the same ingest modules; only
execution mode differs. The original source-specific cursor + 30-day overlap window
was later superseded on 2026-06-04: incremental now re-scans cheap list endpoints in
full, skips immutable per-item fetches, and leaves cursors as audit markers. Absorbed
from ADR-0006 and updated with its supersession note.

## 2026-05-27 — Use pg_trgm for first Korean keyword search

For the first hosted-Postgres-bound search slice, Korean keyword search uses `pg_trgm`
GIN indexes on bill names, bill summaries, and utterance content. PGroonga remains a
stronger multilingual option, but adopting it now would change the local Postgres
runtime before the project proves substring keyword search is insufficient. Absorbed
from ADR-0005.

## 2026-05-27 — Validate minutes HTML before accepting utterances

The meeting-minutes HTML endpoint can transiently return a different meeting's DOM
under parallel scraping, so utterance ingest validates the parsed meeting date
against `meetings.conf_date` before accepting a response. Scraping remains parallel,
but the default worker count is capped at 5 until a later full-load run proves higher
concurrency preserves metadata correctness, not just HTTP success. Absorbed from
ADR-0004.

## 2026-05-27 — Calibrate parallel ingest before full load

The initial 10% load is a calibration phase, not the product goal: it measures worker
counts for unknown National Assembly OpenAPI and meeting HTML limits before attempting
100% collection. For meeting metadata the calibration target is about 500 meetings
across all five source APIs, and per-bill enrichment (`VCONFBILLCONFLIST`) uses the
measured worker policy so the later full load can be fast without blindly increasing
concurrency. Absorbed from ADR-0003.

## 2026-05-27 — Normalize lead proposers and member stubs

The bill API can put multiple lead proposers in `RST_MONA_CD`, and it can reference
MONA_CD values not returned by the member-profile API. Dropping those references or
removing FKs would weaken the core "JOIN by member ID" value, so lead proposers are
normalized into `bill_lead_proposers`, missing members are preserved as name-only
`members` stubs, and `bills.rst_mona_cd` remains only a convenience FK for single-lead
cases. Absorbed from ADR-0002.

## 2026-05-26 — api_catalog covers only pipeline OpenAPI endpoints

`api_catalog` verifies and documents only the PRD-confirmed OpenAPI endpoints used
by the pipeline, with `used_in_pipeline=TRUE`; unused OpenAPI metadata is not
maintained in this repo after the #58 legacy cleanup. This avoided low-ROI
verification of 263 unused APIs while preserving an easy extension path: find and
add the needed endpoint row when the pipeline actually uses it. Later
`ncocpgfiaoituanbr` was added through that path for vote candidate BILL_ID
discovery. Absorbed from ADR-0001 and updated after #58.
