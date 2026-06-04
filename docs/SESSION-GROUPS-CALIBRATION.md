# Session Groups Calibration

This report measures automatic Q&A session_group generation on the
current 10% utterance calibration load. This is a generation-rate and
data-integrity check; semantic accuracy review remains in Slice 9.

## Summary

- Meetings with utterances: 2103
- Skip-target meetings: 739
- Applicable meetings: 1364
- Applicable meetings with groups: 1049 (76.9%)
- Session groups: 30755
- Linked utterances: 920595
- Groups with no detected respondents: 0

## Semantic Review Candidates

- Groups with 50+ utterances: 4675
- Groups with 100+ utterances: 563
- Largest group utterance count: 783

## Integrity

- Skip-target groups: 0
- Missing questioner FK refs: 0
- utterance_count mismatches: 0
- total_chars mismatches: 0
- Invalid respondents JSONB: 0

## By Meeting Type

| Type | Meetings | Skipped | Applicable | Applicable with groups | Groups | Success |
|---|---:|---:|---:|---:|---:|---:|
| 국정감사 | 317 | 0 | 317 | 315 | 13210 | 99.4% |
| 국정조사 | 34 | 0 | 34 | 22 | 1049 | 64.7% |
| 본회의 | 114 | 114 | 0 | 0 | 0 | - |
| 상임위 | 892 | 11 | 881 | 608 | 13539 | 69.0% |
| 소위원회 | 577 | 577 | 0 | 0 | 0 | - |
| 특별위 | 169 | 37 | 132 | 104 | 2957 | 78.8% |
