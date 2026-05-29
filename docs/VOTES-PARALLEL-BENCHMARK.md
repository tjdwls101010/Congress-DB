# Parallel Benchmark

Measured at: `2026-05-27T13:27:57+00:00`

## Selected worker count

`20` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 22.05 | 4.54 |
| 20 | 100 | 100 | 0 | 0.0% | 9.23 | 10.83 |
| 50 | 100 | 100 | 0 | 0.0% | 19.04 | 5.25 |
| 100 | 100 | 100 | 0 | 0.0% | 10.47 | 9.55 |
| 200 | 100 | 99 | 1 | 1.0% | 40.49 | 2.47 |

## Calls/sec chart

```text
  5: ############# 4.54/s
 20: ############################## 10.83/s
 50: ############### 5.25/s
100: ########################## 9.55/s
200: ####### 2.47/s
```

## Sample Errors

- `200` workers: vote rows fetch failed for BILL_ID=PRC_D2W6E0E4I2O9Y2C0O1M9K3W4U6Z4K0: ERROR-300: 필수 값이 누락되어 있습니다. 요청인자를 참고 하십시오.
