# Session Groups Calibration

This report measures automatic Q&A session_group generation on the
current 10% utterance calibration load. This is a generation-rate and
data-integrity check; semantic accuracy review remains in Slice 9.

## Summary

- Meetings with utterances: 500
- Skip-target meetings: 60
- Applicable meetings: 440
- Applicable meetings with groups: 344 (78.2%)
- Session groups: 16313
- Linked utterances: 448558
- Groups with no detected respondents: 2709

## Integrity

- Skip-target groups: 0
- Missing questioner FK refs: 0
- utterance_count mismatches: 0
- total_chars mismatches: 0
- Invalid respondents JSONB: 0

## By Meeting Type

| Type | Meetings | Skipped | Applicable | Applicable with groups | Groups | Success |
|---|---:|---:|---:|---:|---:|---:|
| 국정감사 | 317 | 0 | 317 | 231 | 11867 | 72.9% |
| 국정조사 | 29 | 0 | 29 | 27 | 842 | 93.1% |
| 본회의 | 41 | 41 | 0 | 0 | 0 | - |
| 상임위 | 26 | 0 | 26 | 24 | 436 | 92.3% |
| 소위원회 | 19 | 19 | 0 | 0 | 0 | - |
| 인사청문회 | 56 | 0 | 56 | 52 | 3028 | 92.9% |
| 특별위 | 12 | 0 | 12 | 10 | 140 | 83.3% |
