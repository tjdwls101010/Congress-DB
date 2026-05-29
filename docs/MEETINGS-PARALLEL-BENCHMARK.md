# Parallel Benchmark

Measured at: `2026-05-27T13:32:43+00:00`

## Selected worker count

`5` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 5.01 | 19.94 |
| 20 | 100 | 100 | 0 | 0.0% | 6.07 | 16.47 |
| 50 | 100 | 100 | 0 | 0.0% | 5.53 | 18.07 |
| 100 | 100 | 100 | 0 | 0.0% | 6.58 | 15.20 |
| 200 | 100 | 100 | 0 | 0.0% | 6.02 | 16.61 |

## Calls/sec chart

```text
  5: ############################## 19.94/s
 20: ######################### 16.47/s
 50: ########################### 18.07/s
100: ####################### 15.20/s
200: ######################### 16.61/s
```
