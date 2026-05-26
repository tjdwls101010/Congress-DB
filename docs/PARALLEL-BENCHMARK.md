# Parallel Benchmark

Measured at: `2026-05-26T15:03:14+00:00`

## Selected worker count

`50` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 6.95 | 14.38 |
| 20 | 100 | 100 | 0 | 0.0% | 4.59 | 21.79 |
| 50 | 100 | 100 | 0 | 0.0% | 4.11 | 24.35 |
| 100 | 100 | 100 | 0 | 0.0% | 4.30 | 23.26 |
| 200 | 100 | 100 | 0 | 0.0% | 4.12 | 24.27 |

## Calls/sec chart

```text
  5: ################## 14.38/s
 20: ########################### 21.79/s
 50: ############################## 24.35/s
100: ############################# 23.26/s
200: ############################## 24.27/s
```

<!-- SCRAPE_BENCHMARK_START -->
## Scraping Stage

Measured at: `2026-05-26T23:41:32+00:00`

Selected worker count: `50`

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 50.87 | 1.97 |
| 20 | 100 | 100 | 0 | 0.0% | 29.80 | 3.36 |
| 50 | 100 | 100 | 0 | 0.0% | 25.80 | 3.88 |
| 100 | 100 | 100 | 0 | 0.0% | 32.17 | 3.11 |
| 200 | 100 | 100 | 0 | 0.0% | 33.46 | 2.99 |
<!-- SCRAPE_BENCHMARK_END -->
