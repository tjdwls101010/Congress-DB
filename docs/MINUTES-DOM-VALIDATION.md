# Minutes DOM Validation

This report validates the actual `record.assembly.go.kr` meeting-minutes DOM
across meeting types before bulk utterance scraping.

## Summary

- Checked meetings: 91
- Fetch/HTTP errors: 0
- Parse failures (0 utterances): 0

## By Meeting Type

| Type | Checked | Errors | Parse failures | Min utterances | Max utterances |
|---|---:|---:|---:|---:|---:|
| 국정감사 | 13 | 0 | 0 | 839 | 2677 |
| 국정조사 | 13 | 0 | 0 | 41 | 3914 |
| 본회의 | 13 | 0 | 0 | 1 | 690 |
| 상임위 | 13 | 0 | 0 | 16 | 1728 |
| 소위원회 | 13 | 0 | 0 | 33 | 1351 |
| 인사청문회 | 13 | 0 | 0 | 154 | 2689 |
| 특별위 | 13 | 0 | 0 | 2 | 1390 |

## Sample Details

| mnts_id | Layer | Type | Date | Speakers | Names | Titles | Talk txt | spk_sub | Utterances | First speaker class | Error |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 51887 | old | 국정감사 | 2024-10-07 | 2677 | 2677 | 2677 | 2677 | 2677 | 2677 | `item0 speaker spk_mem` |  |
| 51886 | old | 국정감사 | 2024-10-07 | 1677 | 1677 | 1677 | 1677 | 1677 | 1677 | `item0 speaker spk_mem` |  |
| 51885 | old | 국정감사 | 2024-10-07 | 1854 | 1854 | 1854 | 1854 | 1854 | 1854 | `item0 speaker spk_mem` |  |
| 55735 | recent | 국정감사 | 2025-11-06 | 1978 | 1978 | 1978 | 1978 | 1978 | 1977 | `item0 speaker spk_mem` |  |
| 55734 | recent | 국정감사 | 2025-11-05 | 2557 | 2557 | 2557 | 2557 | 2557 | 2557 | `item0 speaker spk_mem` |  |
| 55723 | recent | 국정감사 | 2025-11-05 | 839 | 839 | 839 | 839 | 839 | 839 | `item0 speaker spk_mem` |  |
| 55755 | recent | 국정감사 | 2025-11-04 | 1156 | 1156 | 1156 | 1156 | 1156 | 1156 | `item0 speaker spk_mem` |  |
| 55638 | recent | 국정감사 | 2025-10-30 | 2193 | 2193 | 2193 | 2193 | 2193 | 2193 | `item0 speaker spk_mem` |  |
| 55635 | recent | 국정감사 | 2025-10-30 | 1642 | 1642 | 1642 | 1642 | 1642 | 1642 | `item0 speaker spk_mem` |  |
| 55603 | recent | 국정감사 | 2025-10-30 | 1734 | 1734 | 1734 | 1734 | 1734 | 1733 | `item0 speaker spk_mem` |  |
| 55595 | recent | 국정감사 | 2025-10-30 | 1263 | 1263 | 1263 | 1263 | 1263 | 1263 | `item0 speaker spk_mem` |  |
| 55553 | recent | 국정감사 | 2025-10-30 | 2486 | 2486 | 2486 | 2486 | 2486 | 2486 | `item0 speaker spk_mem` |  |
| 55550 | recent | 국정감사 | 2025-10-30 | 1565 | 1565 | 1565 | 1565 | 1565 | 1565 | `item0 speaker spk_mem` |  |
| 52050 | old | 국정조사 | 2025-01-14 | 2998 | 2998 | 2998 | 2998 | 2998 | 2998 | `item0 speaker spk_mem` |  |
| 52049 | old | 국정조사 | 2025-01-07 | 168 | 168 | 168 | 168 | 168 | 168 | `item0 speaker spk_mem` |  |
| 52048 | old | 국정조사 | 2024-12-31 | 76 | 76 | 76 | 76 | 76 | 76 | `item0 speaker spk_mem` |  |
| 56623 | recent | 국정조사 | 2026-04-30 | 719 | 719 | 719 | 719 | 719 | 719 | `item0 speaker spk_mem` |  |
| 56610 | recent | 국정조사 | 2026-04-28 | 3221 | 3221 | 3221 | 3221 | 3221 | 3219 | `item0 speaker spk_mem` |  |
| 56581 | recent | 국정조사 | 2026-04-21 | 3240 | 3240 | 3240 | 3240 | 3240 | 3240 | `item0 speaker spk_mem` |  |
| 56566 | recent | 국정조사 | 2026-04-20 | 41 | 41 | 41 | 41 | 41 | 41 | `item0 speaker spk_mem` |  |
| 56573 | recent | 국정조사 | 2026-04-16 | 3753 | 3753 | 3753 | 3753 | 3753 | 3751 | `item0 speaker spk_mem` |  |
| 56547 | recent | 국정조사 | 2026-04-14 | 3916 | 3916 | 3916 | 3916 | 3916 | 3914 | `item0 speaker spk_mem` |  |
| 56537 | recent | 국정조사 | 2026-04-09 | 2840 | 2840 | 2840 | 2840 | 2840 | 2840 | `item0 speaker spk_mem` |  |
| 56535 | recent | 국정조사 | 2026-04-07 | 3798 | 3798 | 3798 | 3798 | 3798 | 3797 | `item0 speaker spk_mem` |  |
| 56497 | recent | 국정조사 | 2026-04-03 | 2791 | 2791 | 2791 | 2791 | 2791 | 2790 | `item0 speaker spk_mem` |  |
| 56442 | recent | 국정조사 | 2026-03-31 | 252 | 252 | 252 | 252 | 252 | 249 | `item0 speaker spk_mem` |  |
| 52598 | old | 본회의 | 2024-11-04 | 5 | 5 | 5 | 5 | 5 | 5 | `item0 speaker spk_mem` |  |
| 52597 | old | 본회의 | 2024-10-04 | 22 | 22 | 22 | 22 | 22 | 21 | `item0 speaker spk_mem` |  |
| 52596 | old | 본회의 | 2024-09-26 | 146 | 146 | 146 | 146 | 146 | 143 | `item0 speaker spk_mem` |  |
| 56654 | recent | 본회의 | 2026-05-08 | 1 | 1 | 1 | 1 | 1 | 1 | `item0 speaker spk_mem` |  |
| 56653 | recent | 본회의 | 2026-05-07 | 90 | 90 | 90 | 90 | 90 | 88 | `item0 speaker spk_mem` |  |
| 56635 | recent | 본회의 | 2026-04-28 | 10 | 10 | 10 | 10 | 10 | 10 | `item0 speaker spk_mem` |  |
| 56585 | recent | 본회의 | 2026-04-23 | 70 | 70 | 70 | 70 | 70 | 69 | `item0 speaker spk_mem` |  |
| 56575 | recent | 본회의 | 2026-04-18 | 17 | 17 | 17 | 17 | 17 | 17 | `item0 speaker spk_mem` |  |
| 56565 | recent | 본회의 | 2026-04-17 | 2 | 2 | 2 | 2 | 2 | 2 | `item0 speaker spk_mem` |  |
| 56545 | recent | 본회의 | 2026-04-13 | 603 | 603 | 603 | 603 | 603 | 603 | `item0 speaker spk_mem` |  |
| 56544 | recent | 본회의 | 2026-04-10 | 21 | 21 | 21 | 21 | 21 | 21 | `item0 speaker spk_mem` |  |
| 56515 | recent | 본회의 | 2026-04-06 | 691 | 691 | 691 | 691 | 691 | 690 | `item0 speaker spk_mem` |  |
| 56498 | recent | 본회의 | 2026-04-03 | 584 | 584 | 584 | 584 | 584 | 584 | `item0 speaker spk_mem` |  |
| 52653 | old | 상임위 | 2024-12-20 | 1298 | 1298 | 1298 | 1298 | 1298 | 1298 | `item0 speaker spk_mem` |  |
| 52665 | old | 상임위 | 2024-12-19 | 22 | 22 | 22 | 22 | 22 | 22 | `item0 speaker spk_mem` |  |
| 52662 | old | 상임위 | 2024-12-19 | 1368 | 1368 | 1368 | 1368 | 1368 | 1368 | `item0 speaker spk_mem` |  |
| 56738 | recent | 상임위 | 2026-05-20 | 16 | 16 | 16 | 16 | 16 | 16 | `item0 speaker spk_mem` |  |
| 56731 | recent | 상임위 | 2026-05-20 | 439 | 439 | 439 | 439 | 439 | 439 | `item0 speaker spk_mem` |  |
| 56736 | recent | 상임위 | 2026-05-19 | 82 | 82 | 82 | 82 | 82 | 82 | `item0 speaker spk_mem` |  |
| 56732 | recent | 상임위 | 2026-05-19 | 282 | 282 | 282 | 282 | 282 | 282 | `item0 speaker spk_mem` |  |
| 56730 | recent | 상임위 | 2026-05-18 | 1548 | 1548 | 1548 | 1548 | 1548 | 1548 | `item0 speaker spk_mem` |  |
| 56695 | recent | 상임위 | 2026-05-15 | 48 | 48 | 48 | 48 | 48 | 48 | `item0 speaker spk_mem` |  |
| 56694 | recent | 상임위 | 2026-05-14 | 35 | 35 | 35 | 35 | 35 | 35 | `item0 speaker spk_mem` |  |
| 56692 | recent | 상임위 | 2026-05-12 | 55 | 55 | 55 | 55 | 55 | 55 | `item0 speaker spk_mem` |  |
| 56710 | recent | 상임위 | 2026-05-11 | 16 | 16 | 16 | 16 | 16 | 16 | `item0 speaker spk_mem` |  |
| 56051 | recent | 상임위 | 2025-12-31 | 1729 | 1729 | 1729 | 1729 | 1729 | 1728 | `item0 speaker spk_mem` |  |
| 52661 | old | 소위원회 | 2024-12-19 | 269 | 269 | 269 | 269 | 269 | 269 | `item0 speaker spk_mem` |  |
| 52652 | old | 소위원회 | 2024-12-19 | 292 | 292 | 292 | 292 | 292 | 292 | `item0 speaker spk_mem` |  |
| 54446 | old | 소위원회 | 2024-11-21 | 1351 | 1351 | 1351 | 1351 | 1351 | 1351 | `item0 speaker spk_mem` |  |
| 56737 | recent | 소위원회 | 2026-05-20 | 109 | 109 | 109 | 109 | 109 | 109 | `item0 speaker spk_mem` |  |
| 56750 | recent | 소위원회 | 2026-05-19 | 306 | 306 | 306 | 306 | 306 | 306 | `item0 speaker spk_mem` |  |
| 56734 | recent | 소위원회 | 2026-05-19 | 198 | 198 | 198 | 198 | 198 | 198 | `item0 speaker spk_mem` |  |
| 56733 | recent | 소위원회 | 2026-05-19 | 514 | 514 | 514 | 514 | 514 | 514 | `item0 speaker spk_mem` |  |
| 56693 | recent | 소위원회 | 2026-05-14 | 33 | 33 | 33 | 33 | 33 | 33 | `item0 speaker spk_mem` |  |
| 56711 | recent | 소위원회 | 2026-05-12 | 624 | 624 | 624 | 624 | 624 | 624 | `item0 speaker spk_mem` |  |
| 56030 | recent | 소위원회 | 2025-12-23 | 115 | 115 | 115 | 115 | 115 | 115 | `item0 speaker spk_mem` |  |
| 55979 | recent | 소위원회 | 2025-12-18 | 83 | 83 | 83 | 83 | 83 | 83 | `item0 speaker spk_mem` |  |
| 55973 | recent | 소위원회 | 2025-12-18 | 271 | 271 | 271 | 271 | 271 | 271 | `item0 speaker spk_mem` |  |
| 55967 | recent | 소위원회 | 2025-12-18 | 258 | 258 | 258 | 258 | 258 | 258 | `item0 speaker spk_mem` |  |
| 52146 | old | 인사청문회 | 2024-07-22 | 1180 | 1180 | 1180 | 1180 | 1180 | 1180 | `item0 speaker spk_mem` |  |
| 52111 | old | 인사청문회 | 2024-07-22 | 1578 | 1578 | 1578 | 1578 | 1578 | 1578 | `item0 speaker spk_mem` |  |
| 52117 | old | 인사청문회 | 2024-07-16 | 1785 | 1785 | 1785 | 1785 | 1785 | 1785 | `item0 speaker spk_mem` |  |
| 56571 | recent | 인사청문회 | 2026-04-15 | 1563 | 1563 | 1563 | 1563 | 1563 | 1563 | `item0 speaker spk_mem` |  |
| 56419 | recent | 인사청문회 | 2026-04-01 | 1963 | 1963 | 1963 | 1963 | 1963 | 1963 | `item0 speaker spk_mem` |  |
| 56427 | recent | 인사청문회 | 2026-03-26 | 724 | 724 | 724 | 724 | 724 | 724 | `item0 speaker spk_mem` |  |
| 56418 | recent | 인사청문회 | 2026-03-23 | 1149 | 1149 | 1149 | 1149 | 1149 | 1149 | `item0 speaker spk_mem` |  |
| 56417 | recent | 인사청문회 | 2026-03-23 | 1176 | 1176 | 1176 | 1176 | 1176 | 1176 | `item0 speaker spk_mem` |  |
| 56201 | recent | 인사청문회 | 2026-01-24 | 154 | 154 | 154 | 154 | 154 | 154 | `item0 speaker spk_mem` |  |
| 56197 | recent | 인사청문회 | 2026-01-23 | 2689 | 2689 | 2689 | 2689 | 2689 | 2689 | `item0 speaker spk_mem` |  |
| 56191 | recent | 인사청문회 | 2026-01-19 | 216 | 216 | 216 | 216 | 216 | 216 | `item0 speaker spk_mem` |  |
| 55454 | recent | 인사청문회 | 2025-10-01 | 2219 | 2219 | 2219 | 2219 | 2219 | 2219 | `item0 speaker spk_mem` |  |
| 55433 | recent | 인사청문회 | 2025-09-24 | 935 | 935 | 935 | 935 | 935 | 935 | `item0 speaker spk_mem` |  |
| 52672 | old | 특별위 | 2024-12-23 | 1390 | 1390 | 1390 | 1390 | 1390 | 1390 | `item0 speaker spk_mem` |  |
| 52674 | old | 특별위 | 2024-12-20 | 9 | 9 | 9 | 9 | 9 | 9 | `item0 speaker spk_mem` |  |
| 52671 | old | 특별위 | 2024-12-18 | 45 | 45 | 45 | 45 | 45 | 45 | `item0 speaker spk_mem` |  |
| 56052 | recent | 특별위 | 2025-12-30 | 2 | 2 | 2 | 2 | 2 | 2 | `item0 speaker spk_mem` |  |
| 56050 | recent | 특별위 | 2025-12-30 | 31 | 31 | 31 | 31 | 31 | 31 | `item0 speaker spk_mem` |  |
| 56034 | recent | 특별위 | 2025-12-29 | 892 | 892 | 892 | 892 | 892 | 892 | `item0 speaker spk_mem` |  |
| 56033 | recent | 특별위 | 2025-12-29 | 172 | 172 | 172 | 172 | 172 | 172 | `item0 speaker spk_mem` |  |
| 56011 | recent | 특별위 | 2025-12-22 | 29 | 29 | 29 | 29 | 29 | 29 | `item0 speaker spk_mem` |  |
| 55974 | recent | 특별위 | 2025-12-18 | 6 | 6 | 6 | 6 | 6 | 6 | `item0 speaker spk_mem` |  |
| 55975 | recent | 특별위 | 2025-12-17 | 16 | 16 | 16 | 16 | 16 | 16 | `item0 speaker spk_mem` |  |
| 52675 | recent | 특별위 | 2024-12-26 | 786 | 786 | 786 | 786 | 786 | 786 | `item0 speaker spk_mem` |  |
| 52673 | recent | 특별위 | 2024-12-24 | 677 | 677 | 677 | 677 | 677 | 677 | `item0 speaker spk_mem` |  |
| 52672 | recent | 특별위 | 2024-12-23 | 1390 | 1390 | 1390 | 1390 | 1390 | 1390 | `item0 speaker spk_mem` |  |
