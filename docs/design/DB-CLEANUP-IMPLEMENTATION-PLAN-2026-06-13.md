# DB Cleanup Implementation Record — 2026-06-13

This document records the schema cleanup audit, the implementation contract created from it, and the resulting implementation status.

Implementation status:

- Implemented: #112, #113, #114, #115, #116.
- Not implemented: #117, because it is a `ready-for-human` design decision and explicitly blocks deletion of `bills.committee` or `bills.proposer` until the PM chooses a replacement/preservation strategy.
- Verification: `make db-migrate`, full `uv run pytest`, `congress_ro` privilege re-application check, and `git diff --check -- . ':!.agents/*'`.

## Goal

Make the database itself a cleaner interface for the future 입법전문가 skill. The skill will query Neon directly through `congress_ro`, so unnecessary schema surface should be physically removed when it is redundant, and operational metadata should be hidden when it is useful for ingestion but noisy for consumers.

## Decision Rule

- Delete fields or indexes when the fact is already represented by a better authoritative structure and deletion does not lose source information.
- Hide fields or tables when they are operationally useful but irrelevant to the skill.
- Keep raw source fields when deletion would lose information that normalized tables cannot reconstruct.
- Add comments, constraints, or views when the relationship is real but not machine-visible enough for an introspecting SQL consumer.

## Live Audit Evidence

The audit was run against the current `congress_ro` surface.

Visible consumer relations:

- Base tables: `bill_coproposers`, `bill_final_outcomes`, `bill_lead_proposers`, `bill_relations`, `bill_source_aliases`, `bills`, `meeting_bills`, `meetings`, `members`, `utterances`, `votes`
- View: `bill_meeting_contexts`
- Hidden from `congress_ro` in the current DB: `ingest_runs`, `ingest_cursors`, `dead_letters`

Largest storage surfaces:

| Relation | Approx rows | Table | Indexes | Total |
|---|---:|---:|---:|---:|
| `utterances` | 1,385,131 | 809 MB | 1016 MB | 1861 MB |
| `bills` | 18,361 | 52 MB | 70 MB | 128 MB |
| `votes` | 473,594 | 59 MB | 51 MB | 110 MB |
| `bill_coproposers` | 206,299 | 30 MB | 31 MB | 61 MB |

Candidate column storage is small except for surrogate identifiers:

| Candidate | Approx payload |
|---|---:|
| `utterances.id` | 11 MB |
| `votes.id` | 3700 kB |
| `bills.committee` | 467 kB |
| `bills.proposer` | 443 kB |
| `bills.rst_mona_cd` | 151 kB |
| `bills.committee_id` | 142 kB |
| `bills.fetched_at` | 143 kB |

The cost conclusion is that Neon savings mostly come from large tables and indexes, not from small text columns. The schema conclusion is still important: small redundant columns can confuse an LLM consumer even when storage savings are minor.

## Implement Now

### 1. Remove `bills.rst_mona_cd`

Audit result:

- `bill_lead_proposers` is the authoritative lead proposer relation.
- `bills.rst_mona_cd` matches the single lead proposer in 17,142 single-lead bills.
- It is NULL for all 191 multi-lead bills.
- There are no `rst_mona_cd` values without a corresponding `bill_lead_proposers` row.

Decision:

Remove `bills.rst_mona_cd` and `idx_bills_rst`. This deliberately revises the prior 2026-06-12 keep decision because the PM clarified that code update cost is acceptable and redundant DB surface should be deleted rather than merely explained.

Implementation notes:

- Update schema, migrations, tests, comments, docs, and ingest code.
- Keep `bill_lead_proposers.order_no`.
- Keep member stubs for lead proposers missing from the current member roster.
- Keep `bills.proposer`; it is not the same thing as `rst_mona_cd`.

Verification:

- Fresh DB reset no longer exposes `bills.rst_mona_cd`.
- Existing hosted DB migration drops the column and index idempotently.
- Ingesting a single-lead bill still creates exactly one `bill_lead_proposers` row.
- Ingesting a multi-lead bill preserves all lead proposers with order.
- Lead proposer queries work only through `bill_lead_proposers`.

### 2. Remove `votes.id`

Audit result:

- Current vote grain is one row per `(bill_id, mona_cd)`.
- Duplicate `(bill_id, mona_cd)` groups: 0.
- The schema already has `UNIQUE (bill_id, mona_cd)`.
- No production query was found that needs `votes.id` as a public identity.

Decision:

Promote `(bill_id, mona_cd)` to the row identity and remove the surrogate `votes.id`, unless implementation uncovers a current source that requires multiple vote events per same bill-member pair.

Implementation notes:

- Before dropping `id`, assert no duplicate `(bill_id, mona_cd)` rows.
- Replace the primary key with `(bill_id, mona_cd)`.
- If the existing unique index is reused as the primary key, confirm constraint names expected by tests.
- Update schema tests and ERD.
- Do not design `vote_events` in this slice. If multiple vote events become a real requirement, pause and create a separate design issue.

Verification:

- Fresh DB reset creates `votes` without `id`.
- Existing hosted DB migration removes `id` and leaves `(bill_id, mona_cd)` as the primary key.
- Ingest remains idempotent for repeated vote loads.
- Duplicate votes for the same bill-member pair are rejected.

### 3. Harden `congress_ro` Grants

Audit result:

- Current live DB hides `ingest_runs`, `ingest_cursors`, and `dead_letters` from `congress_ro`.
- However, the role script still grants `SELECT ON ALL TABLES IN SCHEMA public` and default SELECT on future tables.
- Re-running the role script after cleanup can re-expose operational tables.

Decision:

Replace broad grants with an explicit allowlist for the consumer surface.

Consumer-readable relations should be limited to:

- `members`
- `bills`
- `bill_lead_proposers`
- `bill_coproposers`
- `votes`
- `meetings`
- `utterances`
- `meeting_bills`
- `bill_relations`
- `bill_source_aliases`
- `bill_final_outcomes`
- `bill_meeting_contexts`

Consumer-executable functions should be explicitly granted:

- `search_bills(text, integer)`
- `search_utterances(text, integer)`
- `search_snippet(text, text, integer)`

Implementation notes:

- Remove or reverse default privileges that auto-grant SELECT on future tables to `congress_ro`.
- New consumer tables or views must grant SELECT explicitly in their own migration.
- Keep `congress_ro` read-only: no write, DDL, or owner permissions.

Verification:

- Re-running the role script does not expose operational tables.
- `congress_ro` can run the search functions and select the consumer relations.
- `congress_ro` cannot select `ingest_runs`, `ingest_cursors`, or `dead_letters`.
- `congress_ro` cannot insert, update, delete, or create objects.

### 4. Verify and Drop `idx_utterances_role_meeting_sequence`

Audit result:

- `idx_utterances_role_meeting_sequence` is about 85 MB.
- Live index stats showed only 10 scans.
- The main meeting stream access pattern is already covered by `UNIQUE (meeting_id, sequence)`.
- The index is recreated by both the speaker role migration and speaker role backfill code.

Decision:

Run representative EXPLAIN checks, then drop this index if no real query needs it. This is a cost cleanup, not a semantic schema change.

Implementation notes:

- Remove the index creation from migrations and from the speaker role backfill code if the index is dropped.
- Do not drop `idx_utterances_content_trgm`; it is large but critical to `search_utterances`.
- Do not drop `utterances_pkey` in this round; `search_utterances` returns `utterance_id`.

Verification:

- Fresh DB reset does not create the role index if it is removed.
- Speaker role backfill does not recreate it.
- Meeting stream, search, and regression pack checks still pass.
- Representative role-filter queries either remain acceptable or produce a documented alternative index proposal.

## Do Not Delete in This Round

### `bills.proposer`

Keep. It is a raw source phrase, not just a join cache. The audit found `외 N인` cases where the raw signer count is not fully reconstructable from `bill_coproposers`.

If this is ever deleted, first add a structured replacement for the information that only the raw phrase currently preserves.

### `bills.committee`

Do not delete directly. `committee` and `committee_id` are always populated together in current bills, but deleting the name before creating a canonical committee structure would lose the display name.

If the PM wants physical normalization here, the correct sequence is:

1. Create a canonical `committees` structure or equivalent mapping that preserves `committee_id -> committee_name`.
2. Backfill it from current `bills.committee_id` and `bills.committee`.
3. Add constraints/comments/views that make the mapping visible.
4. Only then remove `bills.committee`.

Do not remove `bills.committee_id`; it is the bill-side committee key.

### `fetched_at`

Keep in raw tables, hide from consumer-facing views. It is ingestion/audit metadata and storage savings are negligible.

### `proc_result` and `cmt_proc_result`

Keep both. They are not duplicates:

- `cmt_proc_result`: committee-stage result.
- `proc_result`: plenary/final processing result.

The audit found 728 bills with only `cmt_proc_result`, 1,064 with only `proc_result`, and 4,404 with both.

### `law_proc_dt`

Keep. It is not promulgation date, but it has a distinct source meaning. Continue warning consumers to use `bill_final_outcomes.promulgation_dt` for promulgation.

### `bill_source_aliases`

Keep. It is tiny but high leverage: 130 relation targets that fail direct `bills.bill_id` join are resolved through this table.

### `utterances.id`

Keep for now. It costs about 11 MB, but `search_utterances` returns `utterance_id` and regression code joins by it. Removing it would be a public interface break and should be a separate design after the skill prototype proves a better identity surface.

## Relationship and Legibility Follow-up

These are not deletion tasks, but they improve the DB as an LLM-readable interface.

- Add a foreign key from `bill_final_outcomes.bill_no` to `bills.bill_no`. Current orphan count is 0, so the relationship is real but not enforced.
- Add missing comments for consumer-visible columns, especially `bill_meeting_contexts` columns, `bill_source_aliases` columns, `bills.committee`, `bills.committee_id`, `votes.bill_id`, `votes.mona_cd`, and `utterances` identity/order fields.
- Consider an index on `bill_source_aliases.canonical_bill_id` only if query plans or growth justify it. The current table is tiny.

## Issue Map

The implementation issues created from this plan were used as the contract for the cleanup branch.

- #112 — `rst_mona_cd` removal. Implemented by migration 017.
- #113 — `votes.id` removal. Implemented by migration 018.
- #114 — `congress_ro` allowlist hardening. Implemented in `db/roles/congress_ro.sql`.
- #115 — `idx_utterances_role_meeting_sequence` verification/removal. Implemented by migration 019 and speaker role backfill cleanup.
- #116 — relationship/comment legibility follow-up. Implemented by migration 020.
- #117 — committee/proposer conditional cleanup decision. Still open for PM decision.
