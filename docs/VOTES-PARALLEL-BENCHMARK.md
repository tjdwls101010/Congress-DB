# Parallel Benchmark

Measured at: `2026-05-26T15:21:24+00:00`

## Selected worker count

`20` (error rate threshold: < 1%)

Selection policy: choose the lowest worker count that stays under the error threshold and reaches at least 95% of the best measured throughput.

## Results

| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 100 | 100 | 0 | 0.0% | 17.40 | 5.75 |
| 20 | 100 | 100 | 0 | 0.0% | 9.67 | 10.34 |
| 50 | 100 | 100 | 0 | 0.0% | 9.55 | 10.47 |
| 100 | 100 | 98 | 2 | 2.0% | 38.43 | 2.60 |
| 200 | 100 | 100 | 0 | 0.0% | 12.55 | 7.97 |

## Calls/sec chart

```text
  5: ################ 5.75/s
 20: ############################## 10.34/s
 50: ############################## 10.47/s
100: ####### 2.60/s
200: ####################### 7.97/s
```

## Sample Errors

- `100` workers: vote rows fetch failed for BILL_ID=PRC_D2D5C1A0B2Z4A1H3I5H2H2F1G5E5M6: ERROR-300: 필수 값이 누락되어 있습니다. 요청인자를 참고 하십시오., vote rows fetch failed for BILL_ID=PRC_R2G6C0X3I1N2L2B0R4G0J4E5E7J7G2: ERROR-300: 필수 값이 누락되어 있습니다. 요청인자를 참고 하십시오.
