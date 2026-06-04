# Hosted Postgres Migration Readiness

Recommendation: `ready_for_human_review`

## Blockers

- None

## Warnings

- session_group semantic accuracy review is incomplete (pending=784, reviewed=0)
- session_group semantic accuracy has no sampled meetings for: 인사청문회

## Latest Backfill Run

- id: `103`
- status: `success`
- started_at: `2026-05-30 00:03:46.987635+00:00`
- finished_at: `2026-05-30 00:12:08.604740+00:00`
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

## Session Group Semantic Accuracy

- signal: `{'available': True, 'labels_path': 'docs/session-group-eval/labels.csv', 'complete': False, 'missing_meeting_types': ('인사청문회',), 'correct_count': 0, 'incorrect_count': 0, 'missing_count': 0, 'pending_count': 784, 'reviewed_count': 0, 'precision': None, 'recall': None, 'by_type': [{'meeting_type': '국정감사', 'correct_count': 0, 'incorrect_count': 0, 'missing_count': 0, 'pending_count': 220, 'precision': None, 'recall': None}, {'meeting_type': '국정조사', 'correct_count': 0, 'incorrect_count': 0, 'missing_count': 0, 'pending_count': 296, 'precision': None, 'recall': None}, {'meeting_type': '상임위', 'correct_count': 0, 'incorrect_count': 0, 'missing_count': 0, 'pending_count': 131, 'precision': None, 'recall': None}, {'meeting_type': '특별위', 'correct_count': 0, 'incorrect_count': 0, 'missing_count': 0, 'pending_count': 137, 'precision': None, 'recall': None}]}`

## Sanity And Completeness

- sanity_check: `{'available': True, 'section_keys': ('S1', 'S2', 'S3', 'S4a', 'S4b', 'S5', 'S6', 'S7'), 'missing_keys': ()}`
- data_completeness: `{'available': True, 'metric_count': 7, 'member_titled_utterances_total': 847480, 'unmapped_member_titled_utterances': 9, 'ambiguous_name_unmapped_utterances': 0, 'member_titled_utterance_mapping_rate_pct': 100.0, 'member_titled_utterance_actionable_mapping_rate_pct': 100.0, 'previous_actionable_mapping_rate_pct': None, 'actionable_mapping_rate_delta_pct': None, 'mapping_rate_regression_warning': False}`

## Row Counts

| Table | Rows |
|---|---:|
| `members` | 306 |
| `bills` | 18345 |
| `bill_lead_proposers` | 17543 |
| `bill_coproposers` | 206138 |
| `votes` | 473594 |
| `meetings` | 2105 |
| `meeting_bills` | 40355 |
| `utterances` | 1378071 |
| `session_groups` | 30755 |
