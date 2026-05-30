# Parallel Benchmark

Measured at: `2026-05-29T14:52:09+00:00`

## Selected worker count

`100` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 1000 | 1000 | 0 | 0.0% | 144.05 | 6.94 |
| 20 | 1000 | 1000 | 0 | 0.0% | 234.72 | 4.26 |
| 50 | 1000 | 1000 | 0 | 0.0% | 115.81 | 8.63 |
| 100 | 1000 | 1000 | 0 | 0.0% | 58.78 | 17.01 |
| 200 | 1000 | 1000 | 0 | 0.0% | 217.29 | 4.60 |

## Calls/sec chart

```text
  5: ############ 6.94/s
 20: ######## 4.26/s
 50: ############### 8.63/s
100: ############################## 17.01/s
200: ######## 4.60/s
```
