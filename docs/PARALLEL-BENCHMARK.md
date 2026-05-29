# Parallel Benchmark

Measured at: `2026-05-27T13:09:55+00:00`

## Selected worker count

`20` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 7.08 | 14.12 |
| 20 | 100 | 100 | 0 | 0.0% | 6.01 | 16.64 |
| 50 | 100 | 100 | 0 | 0.0% | 5.88 | 17.02 |
| 100 | 100 | 100 | 0 | 0.0% | 6.71 | 14.90 |
| 200 | 100 | 100 | 0 | 0.0% | 6.61 | 15.14 |

## Calls/sec chart

```text
  5: ######################### 14.12/s
 20: ############################# 16.64/s
 50: ############################## 17.02/s
100: ########################## 14.90/s
200: ########################### 15.14/s
```

<!-- SCRAPE_BENCHMARK_START -->
## Scraping Stage

Measured at: `2026-05-27T13:49:06+00:00`

Selected worker count: `10`

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 100 | 100 | 0 | 0.0% | 70.46 | 1.42 |
| 5 | 100 | 100 | 0 | 0.0% | 38.78 | 2.58 |
| 10 | 100 | 100 | 0 | 0.0% | 32.02 | 3.12 |
| 20 | 100 | 98 | 2 | 2.0% | 43.66 | 2.29 |
| 40 | 100 | 98 | 2 | 2.0% | 36.32 | 2.75 |

### Sample Errors

- `20` workers: after 4 attempts: minutes metadata mismatch: id=56654 expected_date=2026-05-08 actual_date=2026-05-12 actual_title=제22대국회 제435회 (임시회) 제1차 농림축산식품해양수산위원회(2026.05.12.), after 4 attempts: minutes metadata mismatch: id=56691 expected_date=2026-05-12 actual_date=2026-05-19 actual_title=제22대국회 제435회 (임시회) 제1차 기후에너지환경노동위원회(2026.05.19.)
- `40` workers: after 4 attempts: minutes metadata mismatch: id=56693 expected_date=2026-05-14 actual_date=2026-05-12 actual_title=제22대국회 제435회 (임시회) 제1차 농림축산식품해양수산위원회(2026.05.12.), after 4 attempts: minutes metadata mismatch: id=56732 expected_date=2026-05-19 actual_date=2026-04-30 actual_title=제22대국회 제434회 (임시회·폐회중) 제12차 윤석열정권정치검찰조작기소의혹사건진상규명국정조사특별위원회(2026.04.30.)
<!-- SCRAPE_BENCHMARK_END -->
