# Parallel Benchmark

Measured at: `2026-05-26T23:09:00+00:00`

## Selected worker count

`100` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 6.04 | 16.55 |
| 20 | 100 | 100 | 0 | 0.0% | 5.56 | 18.00 |
| 50 | 100 | 100 | 0 | 0.0% | 5.28 | 18.95 |
| 100 | 100 | 100 | 0 | 0.0% | 3.00 | 33.31 |
| 200 | 100 | 100 | 0 | 0.0% | 2.91 | 34.38 |

## Calls/sec chart

```text
  5: ############## 16.55/s
 20: ################ 18.00/s
 50: ################# 18.95/s
100: ############################# 33.31/s
200: ############################## 34.38/s
```
