# Hosted Postgres Migration Readiness

Recommendation: `ready_for_human_review`

## Blockers

- None

## Warnings

- session_group semantic accuracy is below standalone-use threshold for: 국정감사, 국정조사, 상임위, 특별위; use utterances sequence-window fallback
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

- signal: `{'available': True, 'labels_path': 'docs/session-group-eval/labels.csv', 'complete': True, 'standalone_precision_threshold': 0.9, 'standalone_recall_threshold': 0.7, 'standalone_below_threshold_types': ('국정감사', '국정조사', '상임위', '특별위'), 'missing_meeting_types': ('인사청문회',), 'correct_count': 620, 'incorrect_count': 164, 'missing_count': 3, 'pending_count': 0, 'reviewed_count': 787, 'agent_labeled_count': 787, 'human_labeled_count': 0, 'precision': 0.7908163265306123, 'recall': 0.9951845906902087, 'by_type': [{'meeting_type': '국정감사', 'correct_count': 176, 'incorrect_count': 44, 'missing_count': 3, 'pending_count': 0, 'precision': 0.8, 'recall': 0.9832402234636871}, {'meeting_type': '국정조사', 'correct_count': 207, 'incorrect_count': 89, 'missing_count': 0, 'pending_count': 0, 'precision': 0.6993243243243243, 'recall': 1.0}, {'meeting_type': '상임위', 'correct_count': 115, 'incorrect_count': 16, 'missing_count': 0, 'pending_count': 0, 'precision': 0.8778625954198473, 'recall': 1.0}, {'meeting_type': '특별위', 'correct_count': 122, 'incorrect_count': 15, 'missing_count': 0, 'pending_count': 0, 'precision': 0.8905109489051095, 'recall': 1.0}]}`

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
