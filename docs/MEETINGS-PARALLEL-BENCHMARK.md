# Parallel Benchmark

Measured at: `2026-05-29T06:24:29+00:00`

## Selected worker count

`200` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 1000 | 1000 | 0 | 0.0% | 47.43 | 21.08 |
| 20 | 1000 | 1000 | 0 | 0.0% | 45.88 | 21.80 |
| 50 | 1000 | 1000 | 0 | 0.0% | 44.43 | 22.51 |
| 100 | 1000 | 1000 | 0 | 0.0% | 42.41 | 23.58 |
| 200 | 1000 | 1000 | 0 | 0.0% | 38.70 | 25.84 |

## Calls/sec chart

```text
  5: ######################## 21.08/s
 20: ######################### 21.80/s
 50: ########################## 22.51/s
100: ########################### 23.58/s
200: ############################## 25.84/s
```
