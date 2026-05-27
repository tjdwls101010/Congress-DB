# Supabase Migration Readiness

Recommendation: `not_ready_for_human_review`

## Blockers

- no backfill run found
- sanity_check signal unavailable
- data_completeness signal unavailable

## Latest Backfill Run

- None

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

- sanity_check: `{'available': False, 'section_keys': (), 'missing_keys': ('S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7')}`
- data_completeness: `{'available': False, 'metric_count': 0}`

## Row Counts

| Table | Rows |
|---|---:|
| `members` | 298 |
| `bills` | 1887 |
| `bill_lead_proposers` | 1750 |
| `bill_coproposers` | 19303 |
| `votes` | 45996 |
| `meetings` | 503 |
| `agenda_items` | 2558 |
| `meeting_bills` | 244 |
| `utterances` | 586766 |
| `session_groups` | 17339 |
