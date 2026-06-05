# Hosted Postgres Migration Readiness

Recommendation: `ready_for_human_review`

## Blockers

- None

## Latest Backfill Run

- id: `103`
- status: `success`
- started_at: `2026-05-30 00:03:46.987635+00:00`
- finished_at: `2026-05-30 00:12:08.604740+00:00`
- error: `None`

## Unresolved Dead Letters

- None

## Sanity And Completeness

- sanity_check: `{'available': True, 'section_keys': ('S1', 'S2', 'S3', 'S4a', 'S4b', 'S5', 'S6', 'S7'), 'missing_keys': ()}`
- data_completeness: `{'available': True, 'metric_count': 7}`

## Row Counts

| Table | Rows |
|---|---:|
| `members` | 306 |
| `bills` | 18345 |
| `bill_lead_proposers` | 17543 |
| `bill_coproposers` | 206138 |
| `votes` | 473594 |
| `meetings` | 2105 |
| `meeting_bills` | 40356 |
| `utterances` | 1378071 |
