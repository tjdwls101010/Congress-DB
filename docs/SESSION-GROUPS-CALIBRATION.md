# Session Groups Calibration

This report measures automatic Q&A session_group generation on the
current 10% utterance calibration load. This is a generation-rate and
data-integrity check; semantic accuracy review remains in Slice 9.

## Summary

- Meetings with utterances: 2101
- Skip-target meetings: 739
- Applicable meetings: 1362
- Applicable meetings with groups: 1014 (74.4%)
- Session groups: 28541
- Linked utterances: 853326
- Groups with no detected respondents: 0

## Semantic Review Candidates

- Groups with 50+ utterances: 4347
- Groups with 100+ utterances: 499
- Largest group utterance count: 417

## Integrity

- Skip-target groups: 0
- Missing questioner FK refs: 0
- utterance_count mismatches: 0
- total_chars mismatches: 0
- Invalid respondents JSONB: 0

## By Meeting Type

| Type | Meetings | Skipped | Applicable | Applicable with groups | Groups | Success |
|---|---:|---:|---:|---:|---:|---:|
| 국정감사 | 317 | 0 | 317 | 316 | 13148 | 99.7% |
| 국정조사 | 34 | 0 | 34 | 22 | 929 | 64.7% |
| 본회의 | 114 | 114 | 0 | 0 | 0 | - |
| 상임위 | 890 | 11 | 879 | 601 | 12832 | 68.4% |
| 소위원회 | 577 | 577 | 0 | 0 | 0 | - |
| 특별위 | 169 | 37 | 132 | 75 | 1632 | 56.8% |
