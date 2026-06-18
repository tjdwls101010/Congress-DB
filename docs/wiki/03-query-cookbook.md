# 03 — 질의 쿡북

아래 질의는 모두 라이브 DB에서 검증된 것입니다. 그대로 복사해 쓰고, 키워드·의안번호만 바꾸세요. 더 많은 cross-table 패턴은 [`docs/design/DB-QUERY-GUIDE.md`](../design/DB-QUERY-GUIDE.md)에 있습니다.

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
LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no;   -- ★ 공포는 bill_no로 join
```

## 2. 키워드로 법안 찾기 (검색 함수)

```sql
SELECT bill_no, bill_name, propose_dt FROM search_bills('전세사기', 50);
```
- `bill_name`+`summary`를 부분문자열(ILIKE)로 검색하고, 반환 컬럼은 6개입니다(`bill_id, bill_no, bill_name, propose_dt, snippet, similarity_score`). 질의 문자열이 **본문에 그대로 박혀야** 잡힙니다 — 본문에 없는 별칭은 못 잡습니다(예: `김영란법`→0건). 단 통칭이 summary에 적혀 있으면 잡힙니다(예: `노란봉투법`→1건, 노조법 summary에 등장). 통칭은 정식명으로 치환해 재질의하세요.
- ⚠️ **2글자 이하 질의는 느립니다**(trigram 인덱스 미사용 → 최대 수 초). 3글자 이상 정식명으로 확장하세요(예: 연금→연금법).

## 3. 의제 추적 — 경쟁 법안의 통합 → 처리 (대표 사례)

여러 법안이 하나의 대안으로 통합돼 가결·공포되는 전 과정:

```sql
-- (a) 한 대안에 흡수된 경쟁 원안들의 발의 정당 분포 = 통합/경쟁 구도
WITH absorbed AS (
  SELECT bl.absorbed_bill_id FROM bill_lineage bl WHERE bl.alternative_bill_no = '2209191'
)
SELECT COALESCE(m.poly_nm, '(정당미상)') AS 발의정당, count(DISTINCT a.absorbed_bill_id) AS 원안수
FROM absorbed a
LEFT JOIN bill_lead_proposers lp ON lp.bill_id = a.absorbed_bill_id
LEFT JOIN members m ON m.mona_cd = lp.mona_cd
GROUP BY 1 ORDER BY 2 DESC;
-- 예: 국민연금법 대안 2209191 → 민주 13·국힘 5·조국혁신 4·무소속 2건이 하나로 통합
```

```sql
-- (b) 가장 많은 원안을 통합한 대안 Top 10 (= 가장 치열했던 의제)
SELECT bl.alternative_bill_no, alt.bill_name, count(*) AS 흡수원안수,
       alt.proc_result, o.promulgation_dt
FROM bill_lineage bl
JOIN bills alt ON alt.bill_id = bl.alternative_bill_id
LEFT JOIN bill_final_outcomes o ON o.bill_no = bl.alternative_bill_no
WHERE bl.alternative_bill_id IS NOT NULL
GROUP BY 1,2,4,5 ORDER BY 3 DESC LIMIT 10;
```

## 4. 특정 의원의 발의·공동발의 법안

```sql
WITH member_ref AS (SELECT mona_cd FROM members WHERE hg_nm = '강대식')  -- 동명이인 있으면 mona_cd로 좁히기
SELECT '대표발의' AS role, b.bill_no, b.bill_name, b.proc_result, b.propose_dt
FROM member_ref mr JOIN bill_lead_proposers lp ON lp.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = lp.bill_id
UNION ALL
SELECT '공동발의', b.bill_no, b.bill_name, b.proc_result, b.propose_dt
FROM member_ref mr JOIN bill_coproposers cp ON cp.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = cp.bill_id
ORDER BY propose_dt DESC NULLS LAST;
```

## 5. 위원회·기간별 처리 현황

```sql
SELECT c.committee_name, b.proc_result, count(*) AS bill_count
FROM bills b JOIN committees c ON c.committee_id = b.committee_id
WHERE b.proc_dt >= DATE '2025-01-01' AND b.proc_dt < DATE '2026-01-01'
  AND c.committee_name = '보건복지위원회'
GROUP BY 1,2 ORDER BY 3 DESC;
```

## 6. 정당별 발의·가결 (발의주체 커버리지 주의)

```sql
SELECT m.poly_nm AS 정당, count(*) AS 대표발의,
       count(*) FILTER (WHERE b.proc_result IN ('원안가결','수정가결')) AS 가결
FROM bill_lead_proposers lp JOIN bills b ON b.bill_id = lp.bill_id
JOIN members m ON m.mona_cd = lp.mona_cd
WHERE m.poly_nm IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;
```
⚠️ 위원장 대안·정부제출안은 대표발의자가 없어 이 집계에서 빠집니다 — "정당 귀속 가결"의 부분집계임을 유의.

## 7. 한 법안의 표결 결과 (정당별)

```sql
SELECT poly_nm_at_vote AS 정당, result_vote_mod AS 표결, count(*) AS 수
FROM votes
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2209191')
GROUP BY 1,2 ORDER BY 1,2;
```

## 8. 공포 여부 + "가결인데 공포 없음"(거부권/계류) 구분

```sql
-- 통과한 '법률안'인데 공포 outcome 없음 = 거부권 후보 또는 계류
SELECT b.bill_no, b.bill_name, b.proc_dt,
       (o.plenary_dt > b.proc_dt) AS 거부권후보   -- 본회의 의결일이 처리일보다 늦음 = 재의결
FROM bills b
LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
WHERE b.proc_result IN ('원안가결','수정가결')
  AND b.bill_name ~ '법(률)?안'                    -- 비-법률 의안(결의안 등) 제외
  AND NOT EXISTS (SELECT 1 FROM bill_final_outcomes o2
                  WHERE o2.bill_no = b.bill_no AND o2.promulgation_dt IS NOT NULL)
ORDER BY b.proc_dt DESC NULLS LAST;
```

## 9. 공포된 법 → 법제처 bridge 키 추출

```sql
SELECT b.bill_no, b.bill_name,
       o.prom_no AS 공포번호,            -- ★ 신뢰 가능한 bridge 키 (100% 채움)
       o.promulgation_dt AS 공포일,
       COALESCE(NULLIF(btrim(o.prom_law_nm), ''), b.bill_name) AS 법령명_폴백
FROM bills b JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
WHERE o.promulgation_dt IS NOT NULL
ORDER BY o.promulgation_dt DESC LIMIT 20;
```

## 10. 회의록 발언 검색 + 주변 문맥 읽기

```sql
-- 키워드 발언 검색
SELECT meeting_id, speaker_name, speaker_title, snippet
FROM search_utterances('국민연금', 20);

-- 특정 회의의 발언 stream (sequence 순서로 문맥 복원)
SELECT u.sequence, u.speaker_name, u.speaker_title, u.content
FROM utterances u
WHERE u.meeting_id = '<meeting_id>'
ORDER BY u.sequence;
```
