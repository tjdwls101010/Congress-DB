# Session Groups Calibration

This report measures automatic Q&A session_group generation on the
current 10% utterance calibration load. This is a generation-rate and
data-integrity check; semantic accuracy review remains in Slice 9.

## Summary

- Meetings with utterances: 500
- Skip-target meetings: 60
- Applicable meetings: 440
- Applicable meetings with groups: 411 (93.4%)
- Session groups: 17339
- Linked utterances: 524635
- Groups with no detected respondents: 0

## Semantic Review Candidates

- Groups with 50+ utterances: 2659
- Groups with 100+ utterances: 312
- Largest group utterance count: 266

## Integrity

- Skip-target groups: 0
- Missing questioner FK refs: 0
- utterance_count mismatches: 0
- total_chars mismatches: 0
- Invalid respondents JSONB: 0

## By Meeting Type

| Type | Meetings | Skipped | Applicable | Applicable with groups | Groups | Success |
|---|---:|---:|---:|---:|---:|---:|
| 국정감사 | 317 | 0 | 317 | 316 | 12909 | 99.7% |
| 국정조사 | 29 | 0 | 29 | 17 | 1018 | 58.6% |
| 본회의 | 41 | 41 | 0 | 0 | 0 | - |
| 상임위 | 26 | 0 | 26 | 19 | 422 | 73.1% |
| 소위원회 | 19 | 19 | 0 | 0 | 0 | - |
| 인사청문회 | 56 | 0 | 56 | 53 | 2865 | 94.6% |
| 특별위 | 12 | 0 | 12 | 6 | 125 | 50.0% |
