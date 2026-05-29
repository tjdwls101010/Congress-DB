# Supabase Migration Readiness

Recommendation: `ready_for_human_review`

Operational gate: issue #45 is still required before Supabase migration. This
report is one readiness signal, not final approval to migrate. The final gate is
the clean local 100% backfill + monitored hardening + idempotency rerun described
in [PRE-MIGRATION-BACKFILL-GATE.md](PRE-MIGRATION-BACKFILL-GATE.md).

## Blockers

- None

## Latest Backfill Run

- id: `343`
- status: `success`
- started_at: `2026-05-27 14:11:12.922781+00:00`
- finished_at: `2026-05-27 14:11:16.932376+00:00`
- error: `None`

## Unresolved Dead Letters

- None

## Session Group Integrity

| Metric | Count |
|---|---:|
| `utterance_count_mismatch` | 0 |
| `total_chars_mismatch` | 0 |
| `respondents_format_invalid` | 0 |
| `respondent_empty_groups` | 0 |

## Sanity And Completeness

- sanity_check: `{'available': True, 'section_keys': ('S1', 'S2', 'S3', 'S4a', 'S4b', 'S5', 'S6', 'S7'), 'missing_keys': ()}`
- data_completeness: `{'available': True, 'metric_count': 7}`

## Row Counts

| Table | Rows |
|---|---:|
| `members` | 306 |
| `bills` | 18323 |
| `bill_lead_proposers` | 17521 |
| `bill_coproposers` | 205902 |
| `votes` | 473594 |
| `meetings` | 2103 |
| `meeting_bills` | 40338 |
| `utterances` | 1328745 |
| `session_groups` | 28541 |
