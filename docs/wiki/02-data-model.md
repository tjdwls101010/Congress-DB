# 02 — 데이터 모델

이 DB의 중심은 **의안**(`bills`)이고, 거기에 의원·발의·표결·공포가 붙습니다. 모든 수치는 2026-07-19 적재 기준입니다.

## 법안 생애주기 (한눈에)

```
                       bills (발의된 의안)
  propose_dt ──→ committee_dt ──→ cmt_proc_dt ──→ law_proc_dt ──→ proc_dt
   (발의)        (소관위 회부)     (소관위 처리)    (법사위 처리)   (본회의 처리)
                                                                     │
                                                                     ▼
                   bill_final_outcomes  (bill_no 로 join — bill_id 아님!)
        plenary_dt ──→ govt_transfer_dt ──→ promulgation_dt (+ prom_no, prom_law_nm)
       (본회의 의결)      (정부 이송)             (공포)
```

**생애주기 순서는 컬럼의 물리적 순서와 다릅니다.** `\d+ bills`에 보이는 순서대로 읽으면 단계를 잘못 짚습니다.

> ⚠️ **(대안)·(정부) 법안은 `committee_dt`·`cmt_proc_dt`·`law_proc_dt`가 구조적으로 전부 NULL**입니다 — 원천이 회부·심사 날짜를 주지 않기 때문입니다. 이 날짜를 필수 단계로 가정해 `INNER JOIN`하면 **정작 법이 될 가능성이 가장 높은 대안·정부안이 통째로 빠집니다.** `LEFT JOIN`을 쓰세요.

## 핵심 테이블

### `bills` — 발의된 의안 (19,277건)

- 안정키는 **`bill_no`**(7자리 의안번호). `bill_id`는 source마다 갈릴 수 있어 cross-source 영구키로 쓰면 안 됩니다.
- `proc_result` = 본회의 처리 결과. **`'가결'` 단독값은 존재하지 않습니다** — 통과는 `IN ('원안가결','수정가결')`(1,126 + 499 = 1,625건).
- `proc_result IS NULL`(13,745건, 약 71%)은 **미처리**이지 부결이 아닙니다. 실제 `'부결'`은 2건뿐입니다.
- `cmt_proc_result` = 소관위 처리 결과(예: `대안반영폐기`). 본회의 단계인 `proc_result`와 다른 층입니다.
- `is_law_bill`(생성컬럼) = 공포 대상인 법률안인지. 법률안 19,106 / 비-법률 의안 171.
- ⚠️ `bills`는 **발의된 의안**이지 시행 중인 현행법 본문이 아닙니다.

`proc_result` 실제 분포:

| 값 | 건수 |
| --- | --- |
| (NULL = 미처리) | 13,745 |
| 대안반영폐기 | 3,704 |
| 원안가결 | 1,126 |
| 수정가결 | 499 |
| 철회 | 158 |
| 수정안반영폐기 | 39 |
| 폐기 | 4 |
| 부결 | 2 |

### `members` — 의원 (320명, 현직 299)

- 식별·JOIN은 반드시 **`mona_cd`**로 합니다. **동명이인이 존재**해(예: 박지원 2명) `hg_nm`으로 JOIN하면 서로 다른 두 사람의 데이터가 조용히 합쳐집니다.
- `poly_nm` = *현재* 정당. 명부 동기화 전에 떠난 의원 20명은 NULL이며 전원 `is_incumbent = false`입니다.
- **발의·표결 시점의 정당**이 필요하면 `votes.poly_nm_at_vote`를 쓰세요. `members.poly_nm`을 이 값으로 덮어쓰면 안 됩니다 — 현재값과 시점값은 다른 사실입니다.
- 떠난 의원도 행을 지우지 않고 `is_incumbent = false`로만 표시해 행적 추적이 끊기지 않게 합니다.
- 선거구분은 `orig_nm`에서 파생합니다 — `'비례대표'`면 비례, NULL이면 명부 갭 stub, 그 외는 지역구.

### `committees` — 위원회 dimension (32개)

`bills.committee_id → committees.committee_id`가 법안 소관의 정본입니다. `committee_id`는 **불투명·비연속 코드**(예: 보건복지위 = `9700341`)라 리터럴로 박지 말고, 안정적이고 UNIQUE한 `committee_name`으로 거르세요.

위원회 **membership**(누가 어느 위원인지)은 이 DB에 없습니다 — 범위 밖입니다.

### 발의자: `bill_lead_proposers`(대표) · `bill_coproposers`(공동)

- 둘 다 `(bill_id, mona_cd)` N:M. 전체 발의자 = 두 테이블의 합집합이며, 같은 법안에서 대표와 공동이 겹치는 일은 없습니다.
- ⚠️ **가결 법안의 약 64%는 대표발의자 행이 아예 없습니다** — 위원장 대안(약 768건)과 정부제출안(약 196건)이기 때문입니다. `bill_lead_proposers`만 JOIN해 "정당별 가결 건수"를 세면 절반 이상이 조용히 사라집니다. 위원장 대안의 실제 발의자는 `bill_lineage`로 원안을 되짚어야 나옵니다.
- ⚠️ **정당 NULL 함정** — `poly_nm`이 NULL인 의원 20명 때문에 공동발의 216,537행 중 약 5.2%가 정당 집계에서 조용한 NULL 버킷으로 빠집니다.

### `votes` — 본회의 표결 (482,714행 / 1,627개 의안)

- row 단위 = `bill_id × mona_cd`. **`count(*)`는 표결 event 수가 아니라 의원-표 수입니다.** 의안 수는 `count(DISTINCT bill_id)`.
- 표결 1건당 285~300행(출결·의석 변동으로 가변).
- `result_vote_mod` 실제 분포 — 찬성 348,857 / **불참 121,017** / 반대 7,144 / 기권 5,696.
- ⚠️ **`'불참'`은 빠진 행이 아니라 저장된 값이고 전체의 약 25%입니다.** 출석률·찬성률의 분모를 `count(*)`로 잡으면 결과가 수 %p 조용히 낮아집니다. [04](04-gotchas-and-limits.md) 참조.
- ⚠️ **일 단위 비교·조인은 `vote_date_kst`(생성컬럼)로 합니다.** `vote_date::date`는 세션이 GMT라 하루 어긋나고, `vote_date`(TIMESTAMPTZ)를 DATE 컬럼과 직접 등치 비교하면 조용히 0행입니다.
- ⚠️ **생존편향** — `votes`에는 본회의 표결까지 간 의안만 있고, 그 대부분이 가결된 것들입니다. 여기서 "가결률"을 계산하면 안 됩니다.
- 위원회 단계 표결은 원천 자체에 없습니다.

### `bill_final_outcomes` — 최종 처리·공포 (1,625건, 공포 완료 1,425)

- `bills`와 **`bill_no`로 JOIN**합니다 — `bill_id`가 아닙니다.
- 공포일은 `promulgation_dt`입니다. **`bills.law_proc_dt`는 법사위 처리일이지 공포일이 아닙니다.**
- ⚠️ `plenary_dt`가 `bills.proc_dt`보다 **늦을 수 있습니다** — 대통령 거부권 후 재의결된 경우입니다(26건 확인, 예: 방송법 2024-12-26 → 2025-04-17). 두 날짜가 같다고 가정하지 마세요.

## 원안 → 대안 통합 계보: `bill_lineage` 뷰 (4,204행)

여러 경쟁 법안이 위원회 심사에서 하나의 **위원장 대안**으로 통합되고 원안들이 *대안반영폐기*될 때, 그 연결을 읽는 표면입니다.

```sql
SELECT absorbed_bill_no, relation_type, alternative_bill_no
FROM bill_lineage
WHERE absorbed_bill_no = '2217510';
```

- 1행 = 폐기된 원안 1건. `alternative_bill_no` = 그 내용을 흡수한 canonical 대안.
- 4,204행 중 3,704행이 canonical 대안으로 해소됐고, **500행은 `alternative_bill_id IS NULL`**(미해소)입니다. 미해소여도 "대안에 흡수됐다"는 사실 자체는 authoritative합니다.
- raw 테이블 `bill_relations`·`bill_source_aliases`는 ETL 내부용이라 `congress_ro`에 노출되지 않습니다. alias 해소를 직접 조립하지 말고 이 뷰를 쓰세요.

## 신선도: `data_freshness` 뷰

도메인마다 적재 시점이 다릅니다. **"미공포다"·"계류 중이다"·"최신 지형은 이렇다"를 단정하기 전에 반드시 확인하고, 산출물에 기준일을 병기하세요.**

```sql
SELECT * FROM data_freshness ORDER BY domain;
```

2026-07-19 시점 실측:

| domain | last_ingest_at | latest_fact_date |
| --- | --- | --- |
| `bills` | 2026-07-19 | 2026-07-16 |
| `bill_final_outcomes` | 2026-07-19 | 2026-07-07 |
| `votes` | (없음 — `votes`에 `fetched_at` 컬럼이 없음) | 2026-06-18 |
| `members` | 2026-07-19 | — |
| `bill_relations` | 2026-07-19 | — |

표결의 최신 사실이 의안보다 약 한 달 뒤처져 있다는 점에 주의하세요 — "최근 표결이 없다"가 아니라 "아직 안 들어왔다"일 수 있습니다.

## 공포 → 법제처 bridge

이 DB는 숫자 법령ID나 시행일자를 제공하지 않습니다(법제처 단계). 대신 공포 이력을 bridge 키로 넘깁니다.

| 필드 | 신뢰도 | 용도 |
| --- | --- | --- |
| `prom_no` (공포번호) | 공포 건 100% 채움 | **가장 신뢰 가능한 bridge 키** |
| `promulgation_dt` (공포일) | 높음 | 법령 조회 보조 |
| `prom_law_nm` (공포 법률명) | ⚠️ 낮음 | **단독 사용 금지** |

⚠️ `prom_law_nm`은 66건이 NULL이고(대부분 위원장 대안으로 신설된 제정법), 이름이 있는 것도 약 절반이 공백 제거형이라 법제처(공백 사용)와 exact-match가 되지 않습니다. 이름 매칭이 불가피하면 우리 쪽은 생성컬럼 `prom_law_nm_norm`을 쓰고 **상대측 이름에도 같은 정규화를 적용하세요** — 한쪽만 정규화하면 조용히 0행이 됩니다.

## "발의 ≠ 가결 ≠ 공포 ≠ 현행법"

가장 흔한 범주 오류입니다.

| 개념 | 어디서 | 판정 |
| --- | --- | --- |
| 발의된 의안 | `bills` 전체 | 모든 행 (19,277) |
| 가결 | `bills.proc_result` | `IN ('원안가결','수정가결')` (1,625) |
| 공포된 법 | `bill_final_outcomes` | `promulgation_dt IS NOT NULL` (1,425) |
| 현행법 본문 | **이 DB에 없음** | → 법제처 |

도메인 용어 전체 정의는 [`CONTEXT.md`](../../CONTEXT.md), 스키마 다이어그램은 [`ERD.md`](../design/ERD.md)에 있습니다.
