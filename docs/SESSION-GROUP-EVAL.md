# Session Group Evaluation

This report measures Q&A `session_group` semantic accuracy on sampled
meetings. The CSV label file is the review surface; the code calculates
metrics after a reviewer or agent marks labels.

## Status

- Labeled review status: complete agent first-pass; PM verification pending
- Label file: `docs/session-group-eval/labels.csv`
- Pending auto candidates: 0
- Agent first-pass labels: 787
- Human/PM-reviewed labels: 0

## Metrics

- Correct auto groups: 620
- Incorrect auto groups: 164
- Missing expected groups: 3
- Precision: 79.1%
- Recall: 99.5%

## Metrics By Meeting Type

| Type | Correct | Incorrect | Missing | Pending | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| 국정감사 | 176 | 44 | 3 | 0 | 80.0% | 98.3% |
| 국정조사 | 207 | 89 | 0 | 0 | 69.9% | 100.0% |
| 상임위 | 115 | 16 | 0 | 0 | 87.8% | 100.0% |
| 특별위 | 122 | 15 | 0 | 0 | 89.1% | 100.0% |

## Coverage Notes

- Expected meeting types: 상임위, 특별위, 국정감사, 국정조사, 인사청문회
- Types without sampled meetings: 인사청문회
- Types below recommended sample count: None

## Labeling Guide

- Mark an auto-generated row `correct` if the questioner and start point form a real Q&A meaning unit.
- Mark it `incorrect` if it is a procedural/noisy group rather than a Q&A meaning unit.
- Add a new row with `missing` if the meeting has a real Q&A group that automation missed.
- Leave `label` blank for rows not yet reviewed. PM review is only needed for disputed examples.

## Sampled Meetings

| Type | Meeting ID | Date | Groups | Title |
|---|---:|---|---:|---|
| 상임위 | 56770 | 2026-05-26 | 52 | 행정안전위원회 제2차 (2026. 05. 26.) |
| 상임위 | 56751 | 2026-05-20 | 40 | 국토교통위원회 제2차 (2026. 05. 20.) |
| 상임위 | 56731 | 2026-05-20 | 25 | 외교통일위원회 제1차 (2026. 05. 20.) |
| 상임위 | 56736 | 2026-05-19 | 5 | 기후에너지환경노동위원회 제1차 (2026. 05. 19.) |
| 상임위 | 56732 | 2026-05-19 | 9 | 산업통상자원중소벤처기업위원회 제1차 (2026. 05. 19.) |
| 특별위 | 56618 | 2026-04-28 | 5 | 정치개혁특별위원회 제7차 (2026. 04. 28.) |
| 특별위 | 56555 | 2026-04-13 | 5 | 기후위기특별위원회 제10차 (2026. 04. 13.) (부록) |
| 특별위 | 56539 | 2026-04-09 | 63 | 예산결산특별위원회 제1차 (2026. 04. 09.) |
| 특별위 | 56526 | 2026-04-08 | 31 | 예산결산특별위원회 제2차 (2026. 04. 08.) |
| 특별위 | 56520 | 2026-04-07 | 33 | 예산결산특별위원회 제1차 (2026. 04. 07.) |
| 국정감사 | 55735 | 2025-11-06 | 53 | 대통령비서실|국가안보실|대통령경호처 (2025. 11. 06.) (부록) |
| 국정감사 | 55734 | 2025-11-05 | 12 | 국가인권위원회 (2025. 11. 05.) (부록) |
| 국정감사 | 55723 | 2025-11-05 | 31 | 국회사무처|국회도서관|국회예산정책처|국회입법조사처|국회미래연구원 (2025. 11. 05.) (부록) |
| 국정감사 | 55638 | 2025-10-30 | 68 | 행정안전부|중앙선거관리위원회|진실·화해를위한과거사정리위원회|10·29이태원참사진상규명과재발방지를위한특별조사위원회|인사혁신처|경찰청|소방청 (2025. 10. 30.) (부록) |
| 국정감사 | 55635 | 2025-10-30 | 56 | 해양수산부 (2025. 10. 30.) (부록) |
| 국정조사 | 56610 | 2026-04-28 | 73 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 제11차 (2026. 04. 28.) |
| 국정조사 | 56581 | 2026-04-21 | 56 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 제10차 (2026. 04. 21.) |
| 국정조사 | 56573 | 2026-04-16 | 61 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 제8차 (2026. 04. 16.) |
| 국정조사 | 56547 | 2026-04-14 | 62 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 제7차 (2026. 04. 14.) |
| 국정조사 | 56537 | 2026-04-09 | 44 | 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회 제6차 (2026. 04. 09.) |
