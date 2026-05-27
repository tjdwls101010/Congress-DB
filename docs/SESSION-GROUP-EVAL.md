# Session Group Evaluation

This report measures Q&A `session_group` semantic accuracy on sampled
meetings. The CSV label file is the review surface; the code only
calculates metrics after a human marks labels.

## Status

- Labeling status: pending human labels
- Label file: `docs/session-group-eval/labels.csv`
- Pending auto candidates: 819

## Metrics

- Correct auto groups: 0
- Incorrect auto groups: 0
- Missing expected groups: 0
- Precision: pending
- Recall: pending

## Labeling Guide

- Mark an auto-generated row `correct` if the questioner and start point form a real Q&A meaning unit.
- Mark it `incorrect` if it is a procedural/noisy group rather than a Q&A meaning unit.
- Add a new row with `missing` if the meeting has a real Q&A group that automation missed.
- Leave `label` blank for rows not yet reviewed.

## Sampled Meetings

| Type | Meeting ID | Date | Groups | Title |
|---|---:|---|---:|---|
| 상임위 | 56731 | 2026-05-20 | 25 | 제22대 제435회 제1차 외교통일위원회 (2026년 05월 20일) |
| 상임위 | 56736 | 2026-05-19 | 5 | 제22대 제435회 제1차 기후에너지환경노동위원회 (2026년 05월 19일) |
| 상임위 | 56732 | 2026-05-19 | 9 | 제22대 제435회 제1차 산업통상자원중소벤처기업위원회 (2026년 05월 19일) |
| 상임위 | 56730 | 2026-05-18 | 36 | 제22대 제435회 제1차 행정안전위원회 (2026년 05월 18일) |
| 상임위 | 56692 | 2026-05-12 | 6 | 제22대 제435회 제1차 농림축산식품해양수산위원회 (2026년 05월 12일) |
| 국정감사 | 55735 | 2025-11-06 | 53 | 국회운영위원회 국정감사 회의록 제429회 개회식 (2025-11-06) |
| 국정감사 | 55734 | 2025-11-05 | 12 | 국회운영위원회 국정감사 회의록 제429회 개회식 (2025-11-05) |
| 국정감사 | 55723 | 2025-11-05 | 31 | 국회운영위원회 국정감사 회의록 제429회 개회식 (2025-11-05) |
| 국정감사 | 55755 | 2025-11-04 | 44 | 성평등가족위원회 국정감사 회의록 제429회 개회식 (2025-11-04) |
| 국정감사 | 55638 | 2025-10-30 | 68 | 행정안전위원회 국정감사 회의록 제429회 개회식 (2025-10-30) |
| 국정조사 | 56610 | 2026-04-28 | 73 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 국정조사 회의록 제434회 제11차 (2026-04-28) |
| 국정조사 | 56581 | 2026-04-21 | 56 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 국정조사 회의록 제434회 제10차 (2026-04-21) |
| 국정조사 | 56573 | 2026-04-16 | 71 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 국정조사 회의록 제434회 제8차 (2026-04-16) |
| 국정조사 | 56547 | 2026-04-14 | 62 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 국정조사 회의록 제434회 제7차 (2026-04-14) |
| 국정조사 | 56537 | 2026-04-09 | 34 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 국정조사 회의록 제434회 제6차 (2026-04-09) |
| 인사청문회 | 56571 | 2026-04-15 | 58 | 재정경제기획위원회 인사청문회 회의록 제434회 제3차 (2026-04-15) |
| 인사청문회 | 56419 | 2026-04-01 | 50 | 과학기술정보방송통신위원회 인사청문회 회의록 제433회 제3차 (2026-04-01) |
| 인사청문회 | 56427 | 2026-03-26 | 29 | 행정안전위원회 인사청문회 회의록 제433회 제3차 (2026-03-26) |
| 인사청문회 | 56418 | 2026-03-23 | 52 | 재정경제기획위원회 인사청문회 회의록 제433회 제3차 (2026-03-23) |
| 인사청문회 | 56417 | 2026-03-23 | 45 | 농림축산식품해양수산위원회 인사청문회 회의록 제433회 제2차 (2026-03-23) |
