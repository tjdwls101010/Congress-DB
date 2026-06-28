# 04 — 함정과 범위

이 DB는 국회 원천 데이터를 **그대로(raw fidelity)** 보존합니다 — 결측·표기 불일치가 있고, 모르고 쓰면 *에러 없이 조용히 틀린 답*이 나옵니다. 모든 함정은 컬럼 `COMMENT`에 박혀 있으니 `\d+ <table>`로 직접 확인하는 게 가장 정확합니다. 아래는 가장 자주 걸리는 것들입니다.

## 조용한 오답을 만드는 함정 Top 8

1. **공포는 `bill_no`로 join** — `bill_final_outcomes`엔 `bill_id` 컬럼이 없어 `bill_id`로 join하면 에러(또는 `bill_no↔bill_id` 혼동 시 조용히 0행). 반드시 `o.bill_no = b.bill_no`.

2. **`prom_law_nm` 단독으로 법제처 매칭 금지** — 66건 NULL + 절반이 공백 제거형이라 exact-match 실패. bridge 키는 **`prom_no`**(공포 100% 채움). 이름 매칭 시 공백 제거 + 중점(`ㆍ`U+318D→`·`U+00B7) 정규화.

3. **(대안)·(정부) 법안의 NULL 타임라인** — `committee_dt`·`cmt_proc_dt`·`law_proc_dt`가 구조적으로 NULL(가결의 64~67%). 이 날짜로 `INNER JOIN`하면 법이 된 대안·정부안이 빠집니다.

4. **`proc_result` NULL ≠ 부결** — NULL(약 70%)은 미처리. 통과는 `IN ('원안가결','수정가결')`이고 '가결' 단독값은 없습니다.

5. **발의주체 커버리지** — 가결 법안의 약 64%는 대표발의자가 없습니다(위원장 대안·정부안). `bill_lead_proposers`만 join하면 절반이 누락.

6. **발의자 정당 NULL 20명** — 떠난 의원(`is_incumbent=false`)은 `members.poly_nm`이 NULL. 정당 GROUP BY 시 NULL 버킷으로 빠짐 → `votes.poly_nm_at_vote`로 보정.

7. **동명이인** — 박지원 2명 등. `hg_nm`(이름)으로 join하면 두 사람이 합쳐짐 → 반드시 `mona_cd`로.

8. **`bill_lineage` 0행 ≠ 미흡수** — 소관위 종료 대안반영폐기 원안(`proc_result` NULL)은 뷰에 없음. `bills.cmt_proc_result`도 확인.

## 검색의 한계

- `search_bills`는 **부분문자열(ILIKE)** 검색입니다 — 질의 문자열이 그대로 박혀야 잡힙니다.
  - `bill_name`+`summary`를 검색합니다(반환에 `snippet`·`similarity_score` 포함). 본문에 그대로 없는 별칭·동의어는 못 잡습니다(예: `김영란법`→0건). 단 통칭이 본문에 적혀 있으면 잡힙니다(예: `노란봉투법`→1건, 노조법 summary에 등장). 통칭은 정식명으로 치환·확장하세요.
  - **2글자 이하는 느립니다**(trigram 인덱스 미사용). 3글자+ 정식명으로.
  - 광역 토픽은 `limit`을 크게(200+). 결과가 limit과 정확히 같으면 절단됐을 수 있으니 키워 재질의.

## 이 DB가 담지 않는 것 (범위 밖)

| 원하는 것 | 어디로 |
| --- | --- |
| 현행법·시행령 **본문**, 법령ID, **시행일자** | 법제처 (이 DB는 `prom_no`까지만 bridge) |
| 법안 **전문(full text)** | 이 DB엔 `bill_name` + summary만 |
| **위원회 단계 표결** | 원천 미제공 (`votes`는 본회의만) |
| 위원회 **위원 명부**(누가 위원인지) | 이 DB에 없음 |
| 회의록·**발언**("누가 무엇을 말했나") | 범위 밖 (2026-06-28 제거, 031 → websearch) |
| 청원·공청회·입법예고·여론 | 범위 밖 |

이 경계에 닿는 질문엔 "이 DB 범위 밖"이라고 답하고 외부 소스(법제처 등)로 넘기면 됩니다.

## 데이터 갱신

22대 국회 진행 중이라 **증분 수집**으로 행 수가 계속 늘어납니다. 날짜·건수는 일별 snapshot 기준이며, 쿼리 시점에 따라 달라질 수 있습니다.

## 더 깊이

- 모든 함정의 정량 분포: `\d+ <table>`의 컬럼 COMMENT (DB와 함께 이동, 항상 최신)
- cross-table 레시피: [`docs/design/DB-QUERY-GUIDE.md`](../design/DB-QUERY-GUIDE.md)
- 도메인 용어 사전: [`CONTEXT.md`](../../CONTEXT.md)
