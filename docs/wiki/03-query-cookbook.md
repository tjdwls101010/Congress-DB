# 03 — 질의 쿡북

아래 질의는 모두 라이브 DB에서 검증된 것입니다. 그대로 복사해 쓰고 키워드·의안번호만 바꾸세요. 더 많은 cross-table 패턴은 [`DB-QUERY-GUIDE.md`](../design/DB-QUERY-GUIDE.md)에 있습니다.

각 레시피의 ⚠️는 **그 줄을 빼면 에러 없이 틀린 답이 나오는** 지점입니다.

## 0. 먼저 — 기준일부터 확인

수치를 단정하기 전에 항상 이걸 먼저 돌리고, 결과에 기준일을 병기하세요.

```sql
SELECT * FROM data_freshness ORDER BY domain;
```

도메인마다 적재 시점이 다릅니다. 예컨대 공포 이력이 `bills`보다 며칠 뒤처져 있으면 "미공포 법률안" 수가 실제보다 **과대하게** 나옵니다.

## 1. 한 법안의 생애주기 한눈에

```sql
WITH target AS (SELECT bill_id FROM bills WHERE bill_no = '2218526')
SELECT b.bill_no, b.bill_name, c.committee_name,
       b.propose_dt, b.committee_dt, b.cmt_proc_dt, b.cmt_proc_result,
       b.proc_result, b.proc_dt,
       o.plenary_dt, o.promulgation_dt, o.prom_no, o.prom_law_nm
FROM target t
JOIN bills b ON b.bill_id = t.bill_id
LEFT JOIN committees c ON c.committee_id = b.committee_id
LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no;   -- ⚠️ 공포는 bill_no로 join
```

## 2. 키워드로 법안 찾기

```sql
SELECT bill_no, bill_name, propose_dt FROM search_bills('전세사기', 50);
```

- `bill_name` + `summary`를 **부분문자열(ILIKE)** 로 검색합니다. 반환 컬럼은 `bill_id, bill_no, bill_name, propose_dt, snippet, similarity_score` 6개입니다.
- ⚠️ 질의 문자열이 **본문에 그대로 박혀야** 잡힙니다. 본문에 없는 별칭은 0건입니다(예: `김영란법` → 0건). 단 통칭이 summary에 적혀 있으면 잡힙니다(예: `노란봉투법` → 1건). **통칭은 정식명으로 치환해 재질의하세요.**
- ⚠️ **2글자 이하 질의는 느립니다** — trigram이 3-gram이라 인덱스를 못 타고 seq scan으로 떨어집니다. 3글자 이상 정식명으로 확장하세요(연금 → 연금법).
- ⚠️ 광역 토픽은 `limit`을 크게(200+) 주세요. 결과 수가 limit과 정확히 같으면 절단됐을 수 있습니다.

## 3. 의제 추적 — 경쟁 법안의 통합

```sql
-- (a) 한 대안에 흡수된 원안들의 발의 정당 분포 = 통합/경쟁 구도
WITH absorbed AS (
  SELECT bl.absorbed_bill_id FROM bill_lineage bl WHERE bl.alternative_bill_no = '2209191'
)
SELECT COALESCE(m.poly_nm, '(정당미상)') AS 발의정당,
       count(DISTINCT a.absorbed_bill_id) AS 원안수
FROM absorbed a
LEFT JOIN bill_lead_proposers lp ON lp.bill_id = a.absorbed_bill_id
LEFT JOIN members m ON m.mona_cd = lp.mona_cd
GROUP BY 1 ORDER BY 2 DESC;
```

```sql
-- (b) 가장 많은 원안을 통합한 대안 Top 10 = 가장 치열했던 의제
SELECT bl.alternative_bill_no, alt.bill_name, count(*) AS 흡수원안수,
       alt.proc_result, o.promulgation_dt
FROM bill_lineage bl
JOIN bills alt ON alt.bill_id = bl.alternative_bill_id
LEFT JOIN bill_final_outcomes o ON o.bill_no = bl.alternative_bill_no
WHERE bl.alternative_bill_id IS NOT NULL
GROUP BY 1,2,4,5 ORDER BY 3 DESC LIMIT 10;
```

⚠️ `bill_lineage` 결과가 0행이라고 미흡수는 아닙니다 — 4,204행 중 500행은 canonical 대안으로 해소되지 않아 `alternative_bill_id IS NULL`입니다. `bills.cmt_proc_result`도 함께 확인하세요.

## 4. 특정 의원의 발의·공동발의

```sql
WITH member_ref AS (
  SELECT mona_cd FROM members WHERE hg_nm = '강대식'   -- ⚠️ 동명이인 있으면 mona_cd로 좁힐 것
)
SELECT '대표발의' AS role, b.bill_no, b.bill_name, b.proc_result, b.propose_dt
FROM member_ref mr
JOIN bill_lead_proposers lp ON lp.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = lp.bill_id
UNION ALL
SELECT '공동발의', b.bill_no, b.bill_name, b.proc_result, b.propose_dt
FROM member_ref mr
JOIN bill_coproposers cp ON cp.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = cp.bill_id
ORDER BY propose_dt DESC NULLS LAST;
```

## 5. 위원회·기간별 처리 현황

```sql
SELECT c.committee_name, b.proc_result, count(*) AS bill_count
FROM bills b
JOIN committees c ON c.committee_id = b.committee_id
WHERE b.proc_dt >= DATE '2025-01-01' AND b.proc_dt < DATE '2026-01-01'
  AND c.committee_name = '보건복지위원회'   -- ⚠️ committee_id는 불투명 코드라 이름으로 거를 것
GROUP BY 1,2 ORDER BY 3 DESC;
```

## 6. 정당별 발의·가결

```sql
SELECT m.poly_nm AS 정당, count(*) AS 대표발의,
       count(*) FILTER (WHERE b.proc_result IN ('원안가결','수정가결')) AS 가결
FROM bill_lead_proposers lp
JOIN bills b ON b.bill_id = lp.bill_id
JOIN members m ON m.mona_cd = lp.mona_cd
WHERE m.poly_nm IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;
```

⚠️ **이건 부분집계입니다.** 위원장 대안·정부제출안은 대표발의자가 없어 빠지고, 그게 가결 법안의 약 64%입니다. "정당별 입법 성과"로 쓰지 마세요.

## 7. 한 법안의 표결 — 출석 기준 찬성률

```sql
SELECT
    count(*) FILTER (WHERE result_vote_mod = '찬성')    AS 찬성,
    count(*) FILTER (WHERE result_vote_mod <> '불참')   AS 출석,
    round(100.0 * count(*) FILTER (WHERE result_vote_mod = '찬성')
                / nullif(count(*) FILTER (WHERE result_vote_mod <> '불참'), 0), 1) AS 출석대비_찬성률
FROM votes
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2209191');
```

⚠️ **분모에서 `'불참'`을 빼는 게 핵심입니다.** `'불참'`은 빠진 행이 아니라 저장된 값이고 전체 표의 약 25%(482,714행 중 121,017행)입니다. `count(*)`로 나누면 찬성률이 수 %p 조용히 낮게 나옵니다.

```sql
-- 정당별 표결 분포
SELECT poly_nm_at_vote AS 정당, result_vote_mod AS 표결, count(*) AS 수
FROM votes
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2209191')
GROUP BY 1,2 ORDER BY 1,2;
```

## 8. 날짜로 표결 찾기 — `vote_date_kst`를 쓸 것

```sql
SELECT b.bill_no, b.bill_name, v.vote_date_kst, count(*) AS 표수
FROM votes v
JOIN bills b ON b.bill_id = v.bill_id
WHERE v.vote_date_kst BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'
GROUP BY 1,2,3
ORDER BY 3 DESC;
```

⚠️ **`vote_date::date`나 `vote_date`를 DATE와 직접 비교하지 마세요.** 서버 세션이 GMT라 늦은 시각 표결이 하루 어긋나고, `TIMESTAMPTZ = DATE` 등치 비교는 조용히 0행을 반환합니다. `bills.proc_dt`·`plenary_dt`(DATE)와의 같은-날 매칭도 `vote_date_kst`로 합니다.

## 9. "가결인데 공포 없음" — 거부권/계류 구분

```sql
SELECT b.bill_no, b.bill_name, b.proc_dt,
       (o.plenary_dt > b.proc_dt) AS 거부권후보   -- 본회의 의결일 > 처리일 = 재의결
FROM bills b
LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
WHERE b.proc_result IN ('원안가결','수정가결')
  AND b.is_law_bill                              -- ⚠️ 생성컬럼. 정규식을 직접 쓰지 말 것
  AND NOT EXISTS (SELECT 1 FROM bill_final_outcomes o2
                  WHERE o2.bill_no = b.bill_no AND o2.promulgation_dt IS NOT NULL)
ORDER BY b.proc_dt DESC NULLS LAST;
```

⚠️ `is_law_bill` 필터가 없으면 결의안·감사요구안 같은 **애초에 공포 대상이 아닌 의안 171건**이 "공포 누락"으로 섞여 들어옵니다.

⚠️ 이 결과 건수는 **공포 이력의 신선도에 민감합니다.** 공포 적재가 `bills`보다 뒤처져 있으면 과대 집계됩니다 — 레시피 0으로 기준일을 먼저 확인하세요.

## 10. 공포된 법 → 법제처 bridge 키 추출

```sql
SELECT b.bill_no, b.bill_name,
       o.prom_no            AS 공포번호,      -- ⚠️ 이게 신뢰 가능한 bridge 키 (공포 건 100% 채움)
       o.promulgation_dt    AS 공포일,
       o.prom_law_nm        AS 공포법률명_원본,
       o.prom_law_nm_norm   AS 공포법률명_정규화  -- 생성컬럼: 가운뎃점 통일 + 공백 제거
FROM bills b
JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
WHERE o.promulgation_dt IS NOT NULL
ORDER BY o.promulgation_dt DESC LIMIT 20;
```

⚠️ 이름으로 법제처와 매칭해야 한다면 `prom_law_nm_norm`을 쓰되 **상대측 이름에도 같은 정규화**(가운뎃점 U+318D→U+00B7 통일 + 공백 제거)를 적용하세요. 한쪽만 정규화하면 코드포인트·공백 차이로 조용히 0행이 됩니다.

## 11. 재의결(거부권 후 재표결) 식별

```sql
SELECT b.bill_no, b.bill_name, b.proc_dt AS 최초처리일, o.plenary_dt AS 재의결일
FROM bills b
JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
WHERE o.plenary_dt > b.proc_dt
ORDER BY o.plenary_dt DESC;
```

⚠️ **재의결 표결 자체는 이 DB에 없습니다.** 원천 API가 원표결만 제공해 `votes`에는 최초 표결 한 번만 저장됩니다(26건 확인). 재의결의 찬반 집계가 필요하면 회의록이나 외부 자료로 넘어가야 합니다.
