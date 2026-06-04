# Parallel Benchmark

Measured at: `2026-05-29T06:16:37+00:00`

## Selected worker count

`20` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 1000 | 1000 | 0 | 0.0% | 183.11 | 5.46 |
| 20 | 1000 | 1000 | 0 | 0.0% | 81.62 | 12.25 |
| 50 | 1000 | 1000 | 0 | 0.0% | 85.21 | 11.74 |
| 100 | 1000 | 1000 | 0 | 0.0% | 84.42 | 11.84 |
| 200 | 1000 | 1000 | 0 | 0.0% | 96.81 | 10.33 |

## Calls/sec chart

```text
  5: ############# 5.46/s
 20: ############################## 12.25/s
 50: ############################# 11.74/s
100: ############################# 11.84/s
200: ######################### 10.33/s
```
