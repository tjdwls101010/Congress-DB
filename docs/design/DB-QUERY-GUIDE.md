# DB 활용 가이드 — LLM 직접-SQL 소비자용

이 문서는 입법 스킬(no-SDK, [DECISIONS](DECISIONS.md) 2026-06-10)이 Congress-DB를 **read-only SQL로 직접 조회**할 때 보는 레퍼런스다. 같은 함정 경고는 스키마 컬럼·함수에 `COMMENT`로도 박혀 있다(`db/migrations/011_schema_comments.sql` — `\d+ bills`, `\dt+` 등으로 introspect하면 인라인으로 보임). 도메인 정의는 [CONTEXT.md](../../CONTEXT.md), 관계도는 [ERD.md](ERD.md).

여기 실린 모든 SQL은 `congress_ro`로 실제 실행해 검증했다(감사 2026-06-11).

---

## 0. 접속 & 경계

- **계정:** `congress_ro` (SELECT/EXECUTE만, 쓰기 불가) · **pooled** 연결. 연결 문자열은 `.env.local`의 `CONGRESS_RO_URL`. 자세히는 [DB-ACCESS.md](DB-ACCESS.md).
- **담는 것:** 22대 국회(2024-05-30~)의 **발의된 의안**, **본회의 표결**, **회의록 발언**.
- **안 담는 것:** 시행 중인 **현행법·시행령 본문**(→ 법제처 단계), **위원회 단계 표결**(원천이 안 줌), 정책의제 의미 레이어. → 이런 질문엔 "이 DB 범위 밖"이라고 답할 것.

---

## 1. 테이블 지도

| 테이블 | 무엇 | 핵심 키 | 규모 |
|---|---|---|---|
| `members` | 의원 인적사항 | `mona_cd` (PK) | 320 (현직 300) |
| `bills` | **발의된** 의안 | `bill_id` (PK), `bill_no` (안정키) | 18,361 |
| `bill_lead_proposers` | 대표발의 N:M | `bill_id`×`mona_cd` | |
| `bill_coproposers` | 공동발의 N:M | `bill_id`×`mona_cd` | |
| `votes` | 본회의 표결 (의원별 1행) | `(bill_id, mona_cd)` | ~474k행 / 1,595 법안 |
| `utterances` | 회의 발언 stream | `(meeting_id, sequence)` | ~1.38M행 |
| `meetings` | 회의록 인스턴스 | `mnts_id` (PK) | 2,105 |
| `meeting_bills` | 회의↔법안 N:M | `(meeting_id, bill_id)` | 부분 커버리지 |
| `bill_relations` | 대안/수정안 흡수 관계 | `absorbed_bill_id` (PK) | 3,715 |
| `bill_source_aliases` | source별 BILL_ID → canonical | `(source, source_bill_id)` | |
| `bill_final_outcomes` | 정부이송·**공포** 이력 | `bill_no` (PK) | 1,593 |
| `speaker_title_role_map` | (audit) 직함→역할 분류 | `speaker_title` (PK) | ~3,100 직함 |

운영 테이블(`api_catalog`, `ingest_runs`, `ingest_cursors`, `dead_letters`)은 스킬 조회 대상이 아니다.

---

## 2. 반드시 지킬 규칙 — 안 지키면 *그럴듯하게* 틀린다

1. **공포일은 `bill_final_outcomes.promulgation_dt`. `bills.law_proc_dt`가 아니다.**
   `law_proc_dt`는 법사위 처리일이며 검증 결과 **520/520건 모두** 공포일과 다르다(게다가 종종 NULL).
2. **통과 = `proc_result IN ('원안가결','수정가결')`.** `'가결'` 단독값은 **없다**(0행). `proc_result IS NULL`은 미처리(전체의 ~70%)이지 부결이 아니다.
3. **`utterances`↔`members`는 LEFT JOIN.** `speaker_mona_cd`는 비-의원 화자(장관·차관·증인 등)에서 NULL이고 그 비율이 **38.5%**다. INNER JOIN하면 장관 발언까지 조용히 사라진다.
4. **"정부측 발언" ≠ `speaker_role IN ('국무위원(장관)','차관')`만.** 금융위원장·공정거래위원장·경찰청장·법원행정처장 등은 `'기타'`에 묻혀 있다(§4 Q4 참조).
5. **`votes`는 본회의 전용·의원별 행.** `count(*)`는 표결 횟수가 아니다(법안당 ~297행). 표결된 법안 수는 `count(DISTINCT bill_id)`. **위원회 표결은 데이터에 없다.**
6. **대안 체인은 `bill_relations.alternative_bill_id`를 `bills.bill_id`로 바로 join하면 169건 샌다.** `bill_source_aliases` 경유로 canonical 해소(§4 Q9).
7. **떠난 의원 정당은 `votes.poly_nm_at_vote`.** `members.poly_nm`은 그들에서 NULL이다(20명).
8. **`meeting_bills`는 커버리지가 부분적**(법안 ~85%·회의 ~59%만 연결). 빈 결과가 "논의 안 됨"을 뜻하지 않으니, 답에 이 한계를 밝혀라.

---

## 3. 어휘 — `WHERE` 짜기 전에 알아야 할 값

**`bills.proc_result`** (NULL=미처리 ~70%):
`원안가결`(1,110) · `수정가결`(483) · `대안반영폐기`(3,676) · `수정안반영폐기`(39) · `철회`(154) · `폐기`(4) · `부결`(2)

**`votes.result_vote_mod`:** `찬성`(341k) · `불참`(119k) · `반대`(7.1k) · `기권`(5.6k) — 불참 ~25%, 찬성률 계산 시 분모 정의 주의.

**`utterances.speaker_role`** (7종 enum): `의원`(848k) · `기타`(263k) · `국무위원(장관)`(102k) · `차관`(77k) · `증인`(56k) · `전문위원`(22k) · `참고인`(10k)

**`meetings.meeting_type`** (7종 enum): `상임위`(894) · `소위원회`(577) · `국정감사`(317) · `특별위`(169) · `본회의`(114) · `국정조사`(34) · `인사청문회`(현재 0행)

---

## 4. Join 레시피 + Canonical 쿼리 (전부 검증됨)

### Q1. 통과한 법안
```sql
SELECT bill_no, bill_name, proc_result, proc_dt
FROM bills
WHERE proc_result IN ('원안가결','수정가결')
ORDER BY proc_dt DESC NULLS LAST;
```

### Q2. 한 법안이 언제 의결·공포됐나 (law_proc_dt 쓰지 말 것)
```sql
SELECT b.bill_no, b.bill_name,
       o.plenary_dt      AS 본회의의결일,
       o.promulgation_dt AS 공포일,
       o.prom_no         AS 공포번호
FROM bills b
JOIN bill_final_outcomes o ON o.bill_no = b.bill_no   -- ★ bill_no로 join (bill_id 아님)
WHERE b.bill_no = '2213457';   -- 예: 양자과학기술법 → 공포 2026-06-09 (law_proc_dt는 NULL)
```

**공포 완전성 — "통과했는데 공포 없음"을 [1] 갭으로 단정하기 전에:** `bills`에는 법률안 외 **비-법률 의안**(결의안·동의안·승인안·감사요구안·규칙안·각종 `~의 건`·기금운용계획변경안·국정조사계획서 등 약 169건)이 섞여 있고, 이들은 통과해도 **공포 대상이 아니다**(not_promulgable, 예: `2207635` "의대정원…감사요구안" 원안가결). 그래서 "가결인데 공포 outcome 없음"은 **법률안일 때만** 진짜 [1] 갭이다. 비-법률을 *열거*하지 말고 **양성 법률안 필터** `bill_name ~ '법(률)?안'`(비-법률과 오탐 0 검증)로 거른다 — 분류 컬럼은 두지 않으니 소비자가 패턴으로 판정한다.
```sql
-- 통과한 '법률안'인데 공포 outcome이 없음 = pending 또는 진짜 [1] 갭 (비-법률 의안 제외)
SELECT b.bill_no, b.bill_name, b.proc_dt
FROM bills b
WHERE b.proc_result IN ('원안가결','수정가결')
  AND b.bill_name ~ '법(률)?안'                       -- 법률안류만 (결의안/동의안/감사요구안 등 제외)
  AND NOT EXISTS (SELECT 1 FROM bill_final_outcomes o
                  WHERE o.bill_no = b.bill_no AND o.promulgation_dt IS NOT NULL)
ORDER BY b.proc_dt DESC NULLS LAST;   -- 현재 59건
```
공포일은 있으나 `prom_law_nm`(공포 법률명)이 NULL인 **66건**은 전부 법률안의 실제 [1] 품질 갭(원천 ALLBILL 미제공, 숫자 법령ID도 없음 → [3] 법제처 bridge 몫). 이름에서 유도해 채우지 말 것.

### Q3. 한 의원의 표결 성향
```sql
SELECT m.hg_nm, v.result_vote_mod, count(*)
FROM votes v JOIN members m ON m.mona_cd = v.mona_cd
WHERE m.hg_nm = '남인순'                  -- 동명이인 가능 → 확실히는 m.mona_cd로
GROUP BY 1, 2 ORDER BY 3 DESC;
```

### Q4. "정부측" 발언 — 장관·차관 + 기타에 묻힌 정부기관장
```sql
-- (a) 부처 장·차관
SELECT * FROM utterances WHERE speaker_role IN ('국무위원(장관)','차관');

-- (b) '기타'에 묻힌 정부기관장 직함 후보부터 확인 (audit 테이블)
SELECT speaker_title, n_utterances
FROM speaker_title_role_map
WHERE speaker_role = '기타'
  AND (speaker_title LIKE '%위원장' OR speaker_title LIKE '%청장'
       OR speaker_title LIKE '%처장' OR speaker_title LIKE '%실장'
       OR speaker_title LIKE '%총재'  OR speaker_title LIKE '%원장')
ORDER BY n_utterances DESC;
-- → 법원행정처장·산림청장·금융위원장·금융감독원장·경찰청장·국가인권위원장 …
--   원하는 직함을 골라 utterances.speaker_title IN (…)으로 (b)를 (a)에 UNION.
```

### Q5. 키워드 검색 (DB 내장 함수 — 직접 trigram 짜지 말 것)
```sql
SELECT * FROM search_bills('전세사기', 20);       -- bill_name+summary 유사도 검색
SELECT * FROM search_utterances('의대정원', 20);  -- 발언 content 검색 (장관 발언도 포함)
```

### Q6. 한 법안이 논의된 회의 (커버리지 부분적임을 밝힐 것)
```sql
SELECT mt.conf_date, mt.meeting_type, mt.comm_name, mt.title
FROM meeting_bills mb
JOIN meetings mt ON mt.mnts_id = mb.meeting_id
WHERE mb.bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2213457')
ORDER BY mt.conf_date;
-- 증거 강도(회의 fanout)는 Q11/bill_meeting_contexts 참조: 붐비는 회의 발언을 이 법안 직접 증거로 단정 금지.
```

### Q7. 대표발의를 많이 한 의원 (free-text 아닌 정규화 테이블로)
```sql
SELECT m.hg_nm, m.poly_nm, count(*) AS n
FROM bill_lead_proposers lp JOIN members m ON m.mona_cd = lp.mona_cd
GROUP BY 1, 2 ORDER BY 3 DESC;
-- poly_nm이 · (NULL)인 떠난 의원은 votes.poly_nm_at_vote로 시점 정당 확인.
```

### Q8. 한 법안의 본회의 표결 찬반
```sql
SELECT result_vote_mod, count(*)
FROM votes
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2213457')
GROUP BY 1 ORDER BY 2 DESC;
```

### Q9. 폐기된 원안 → 흡수한 대안(canonical) 해소
```sql
SELECT a0.bill_no AS 원안, r.relation_type,
       COALESCE(bd.bill_no, bc.bill_no) AS 대안_canonical
FROM bill_relations r
JOIN bills a0           ON a0.bill_id = r.absorbed_bill_id
LEFT JOIN bills bd      ON bd.bill_id = r.alternative_bill_id           -- 직접 match
LEFT JOIN bill_source_aliases al ON al.source_bill_id = r.alternative_bill_id
LEFT JOIN bills bc      ON bc.bill_id = al.canonical_bill_id            -- alias 경유
WHERE r.relation_type = '대안반영';
```

### Q10. 한 회의의 발언자 역할 분포 (LEFT JOIN — 비의원 포함)
```sql
SELECT u.speaker_role, count(*)
FROM utterances u
WHERE u.meeting_id = 12345        -- mnts_id
GROUP BY 1 ORDER BY 2 DESC;
```

### Q11. 회의 evidence 강도 — fanout 주의 (발언을 특정 법안에 단정 금지)
한 회의에 수십~수백 법안이 함께 걸리므로(평균 32, p90 75, max 756), "이 회의에서 다뤄짐"을 특정 법안의 직접 발언 증거로 단정하면 과잉주장이 된다. `bill_meeting_contexts` 뷰가 회의 fanout과 회의-단위 발언 통계를 한 자리에 준다.
```sql
SELECT comm_name, conf_date, linked_bill_count, utterance_count, utterances_by_role
FROM bill_meeting_contexts
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2213457')
ORDER BY linked_bill_count DESC;
-- linked_bill_count 클수록(예: 45) 이 회의 발언을 해당 법안 직접 증거로 보기 어려움 → raw count로 판단(버킷 라벨 없음).
-- evidence_scope='meeting_level': 발언↔특정 법안 직접 귀속은 원천이 안 줌. 답에 이 한계를 밝힐 것.
-- 결과가 0행이어도 미논의가 아님(meeting_bills 커버리지 부분적, §5).
```

### Q12. 회의 소관위 ↔ 법안 소관위 연결 (comm_name → committee_id)
위원회 정체성이 `bills.committee`(31종)·`bills.committee_id`(31종, 18,161/18,361 채움)·`meetings.comm_name`(38종)으로 흩어져 있다. `meetings`엔 committee_id가 없어 회의 소관과 법안 소관을 잇으려면 **공백 정규화**가 필요하다(`12.29 여객기…` vs `12.29여객기…` 같은 공백변형 중복). 새 canonical 테이블은 두지 않고 아래 JOIN으로 도출한다.
```sql
SELECT mt.comm_name, b.committee_id, b.committee AS bills_committee
FROM (SELECT DISTINCT comm_name FROM meetings WHERE comm_name IS NOT NULL) mt
LEFT JOIN (SELECT DISTINCT committee, committee_id FROM bills WHERE committee IS NOT NULL) b
  ON regexp_replace(b.committee, '\s', '', 'g') = regexp_replace(mt.comm_name, '\s', '', 'g')
ORDER BY b.committee_id NULLS LAST;
-- 38종 중 30종 매칭. committee_id가 NULL인 8종은 1회성 인사청문·국정조사·연금개혁 특위로
-- 법안이 회부되지 않는 회의-전용 위원회 — 누락이 아니라 정상(이름기반 매핑은 best-effort, 강제 FK 아님).
```
한 의제가 어느 소관위 경로로 움직였는지 볼 때는 문자열 group by 대신 이 매핑으로 법안·회의를 한 `committee_id`로 묶는다. 위원회 **membership**(누가 위원인지)은 이 DB에 없다(범위 밖).

---

## 5. 커버리지·결측 — 답에 한계를 밝혀라

| 영역 | 상태 | 영향 |
|---|---|---|
| `bills.summary` | 233건 NULL (원천 미제공) | summary 키워드 검색이 그만큼 누락 |
| 공포 완전성 | 법률안 66건 `prom_law_nm` NULL + 59건 공포 outcome 없음 | "통과=공포"로 단정 말 것; 비-법률 의안은 not_promulgable(정상) |
| `meeting_bills` | 법안 15%·회의 41% 미연결 | "논의된 회의"가 부분 목록일 수 있음 |
| 위원회 식별 | `meetings.comm_name`(38종)에 committee_id 없음; 8종은 1회성 특위(회의-전용) | 회의↔법안 소관위는 공백 정규화 JOIN(Q12); 위원회 membership은 데이터에 없음 |
| `members` (떠난 20명) | `poly_nm`·프로필 NULL | 정당은 `votes.poly_nm_at_vote`로 |
| `utterances.speaker_mona_cd` | 38.5% NULL (비-의원) | members INNER JOIN 금지 |
| `bill_relations` 39건 | 수정안 source에 안정키 없음 | 대안 체인 일부 끊김 |
| 위원회 표결 | 데이터에 **없음** | "위원회 표결" 질문엔 범위 밖이라 답 |

이 결측들은 대부분 `dead_letters`에 **없다**(원천이 안 주는 accepted-gap이므로). 결측 여부를 `dead_letters`만으로 판단하지 말 것.
