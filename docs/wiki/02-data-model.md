# 02 — 데이터 모델

> **회의·발언 도메인 제거(2026-06-28, 031):** `meetings`·`meeting_bills`·`utterances` 테이블, `bill_meeting_contexts` 뷰, `search_utterances` 함수는 삭제됐습니다. 심의 *진행·상태*는 구조화 테이블(`bills.proc_result`·`bill_lineage`·`bill_final_outcomes`)이 답하고, 발언 내용("누가 무엇을 말했나") 분석은 이 DB 범위 밖(→ websearch)입니다. 자세한 배경은 [`docs/design/DECISIONS.md`](../design/DECISIONS.md) 2026-06-28.

## 법안 생애주기 (한눈에)

```
                bills (발의된 의안)
  propose_dt ──→ committee_dt ──→ cmt_proc_dt ──→ law_proc_dt ──→ proc_dt
   (발의)        (소관위 회부)     (소관위 처리)    (법사위 처리)   (본회의 처리)
                                                                     │
                                                                     ▼
            bill_final_outcomes (공포, bill_no로 join)
        plenary_dt ──→ govt_transfer_dt ──→ promulgation_dt (+ prom_no, prom_law_nm)
        (본회의 의결)    (정부 이송)          (공포)
```

⚠️ **(대안)·(정부) 법안은 `committee_dt`·`cmt_proc_dt`·`law_proc_dt`가 구조적으로 NULL**입니다(원천이 회부/심사 날짜를 안 줌). 이 날짜들을 필수 단계로 가정해 `INNER JOIN`하면 정작 법이 된 대안·정부안이 빠집니다. 자세한 분포는 `\d+ bills`의 `committee_dt` COMMENT 참조.

## 핵심 테이블

### `bills` — 발의된 의안 (중심 테이블)
- 안정키는 **`bill_no`**(7자리 의안번호). `bill_id`는 source마다 갈릴 수 있으니 cross-source 영구키로 쓰지 마세요.
- `proc_result` = 본회의 처리 결과. 통과는 `IN ('원안가결','수정가결')` — '가결' 단독값은 없습니다. NULL(약 70%)은 미처리이지 부결이 아닙니다.
- `cmt_proc_result` = 소관위 처리 결과(예: `대안반영폐기`). `proc_result`(본회의)와 다른 단계입니다.
- ⚠️ `bills`는 **발의된 의안**이지 시행 중인 현행법 본문이 아닙니다(현행법은 법제처 소관, 이 DB 범위 밖).

### `members` — 의원 (320명)
- 식별·join은 반드시 **`mona_cd`**로. 동명이인 존재(예: 박지원 2명) — `hg_nm`(이름)으로 join하면 두 사람이 섞입니다.
- `poly_nm` = 현재 정당. 명부 동기화 전 떠난 의원 20명은 NULL(전원 `is_incumbent=false`). 발의 시점 정당이 필요하면 `votes.poly_nm_at_vote`를 프록시로 쓰세요.

### `committees` — 위원회 (dimension)
- `bills.committee_id → committees.committee_id`가 법안 소관 정본. `committee_id`는 불투명 코드라 리터럴로 박지 말고 `committee_name`으로 거르세요.

### 발의자: `bill_lead_proposers` (대표) · `bill_coproposers` (공동)
- 둘 다 `(bill_id, mona_cd)` N:M. 총 발의자 = 두 테이블 합집합.
- ⚠️ **가결 법안의 약 64%는 대표발의자가 없습니다**(위원장 대안·정부제출안). `bill_lead_proposers`만 join해 "정당별 가결"을 세면 절반 이상이 조용히 누락됩니다.

### `votes` — 본회의 표결 (약 47만 행)
- row 단위 = `bill_id × mona_cd`(의원당 1행). `count(*)`는 표결 event 수가 아니라 의원-표 수입니다.
- `poly_nm_at_vote` = 표결 시점 정당. `result_vote_mod` = 찬성/반대/기권/불참.

### `bill_final_outcomes` — 최종 처리·공포 (**`bill_no`로 join**)
- `bills`와 **`bill_no`로 join**합니다(`bill_id` 아님!).
- 공포일 = `promulgation_dt`. `bills.law_proc_dt`(법사위 처리일)와 혼동 금지.

## 원안 → 대안 통합 계보: `bill_lineage` 뷰

여러 경쟁 법안이 위원회 심사에서 하나의 **위원장 대안**으로 통합(대안반영폐기)되는 과정을 추적합니다.

```sql
SELECT absorbed_bill_no, relation_type, alternative_bill_no
FROM bill_lineage
WHERE absorbed_bill_no = '2217510';
```

- 1행 = 1 폐기 원안. `alternative_bill_no` = 흡수한 canonical 대안.
- ⚠️ **커버리지 caveat**: 소관위에서 종료돼 본회의 `proc_result`가 NULL이고 `cmt_proc_result`만 `대안반영폐기`인 원안은 원천 미수집이라 뷰에 없습니다. **결과 0행 ≠ 미흡수** — `bills.cmt_proc_result`도 함께 확인하세요.

## 공포 → 외부 법령 bridge (법제처 연결)

이 DB는 숫자 법령ID·시행일자를 제공하지 않습니다(법제처 단계). 대신:

| 필드 | 신뢰도 | 용도 |
| --- | --- | --- |
| `prom_no`(공포번호) | 공포 100% 채움 | **가장 신뢰 가능한 bridge 키** |
| `promulgation_dt`(공포일) | 높음 | 법령 조회 보조 |
| `prom_law_nm`(공포 법률명) | ⚠️ 낮음 | **단독 사용 금지** |

⚠️ `prom_law_nm`은 66건이 NULL(위원장 대안 신규 제정법)이고, 이름 있는 것의 절반이 공백 제거형이라 법제처(공백 사용)와 exact-match가 안 됩니다. 이름 매칭이 필요하면 양쪽 공백 제거 + 중점 정규화(`ㆍ`U+318D→`·`U+00B7), NULL이면 `bills.bill_name` 폴백. **bridge 키는 `prom_no`를 쓰세요.**

## "발의 ≠ 가결 ≠ 공포 ≠ 현행법" 구분

| 개념 | 어디서 | 판정 |
| --- | --- | --- |
| 발의된 의안 | `bills` 전체 | 모든 행 |
| 가결 | `bills.proc_result` | `IN ('원안가결','수정가결')` |
| 공포된 법 | `bill_final_outcomes` | `promulgation_dt IS NOT NULL` |
| 현행법 본문 | **이 DB에 없음** | → 법제처 |

가결됐지만 아직 공포 안 된 법률안(거부권/계류)도 식별 가능합니다 — [03 쿡북](03-query-cookbook.md) 참조.

도메인 용어 전체는 [`CONTEXT.md`](../../CONTEXT.md), 스키마 다이어그램은 [`docs/design/ERD.md`](../design/ERD.md).
