# DB Query Guide — 직접 SQL 소비자용

스킬, AI agent, 개발자가 Congress-DB를 **read-only SQL로 직접 조회**할 때 보는 보조 레퍼런스다. 이 저장소의 목표는 SDK/wrapper가 아니라 DB 자체를 명확한 interface로 만드는 것이다.

**먼저 DB를 introspect하라.** 구조(테이블·컬럼·타입·FK)는 [`db/schema.sql`](../../db/schema.sql)과 [ERD.md](ERD.md)에, **함정·어휘·커버리지 경고는 각 테이블·컬럼의 `COMMENT`에** 박혀 있어 `\d+ <table>`로 바로 보인다 — 예: "`bills.law_proc_dt`는 공포일이 아니다", "`utterances`는 LEFT JOIN(38.5% 비-의원)", "`speaker_role` '기타'에 정부측 묻힘", "`proc_result`에 '가결' 단독값 없음" 등 모든 함정이 그 컬럼 COMMENT에 있다. 도메인 정의는 [CONTEXT.md](../../CONTEXT.md).

이 문서는 COMMENT를 반복하지 않고, introspection만으로는 조립하기 어려운 **여러 테이블에 걸친 패턴**만 담는다. 여기 실린 대표 질의 형태는 sentinel fixture 기반 테스트(`tests/test_direct_sql_contract.py`)와 regression pack으로 검증한다.

---

## 0. 접속 & 경계 (introspect로는 안 보이는 메타)

- **계정:** `congress_ro` (SELECT/EXECUTE만, 쓰기 불가) · **pooled**. 연결 문자열은 `.env.local`의 `CONGRESS_RO_URL`. 자세히는 [DB-ACCESS.md](DB-ACCESS.md).
- **담는 것:** 22대 국회(2024-05-30~)의 **발의된 의안** · **본회의 표결** · **회의록 발언**.
- **안 담는 것:** 시행 중인 **현행법·시행령 본문**(→ 법제처 단계) · **위원회 단계 표결**(원천이 안 줌) · 정책의제 의미 레이어. → 이런 질문엔 "이 DB 범위 밖"이라고 답할 것.
- **검색은 DB 내장 함수로**(직접 trigram 짜지 말 것): `search_bills('전세사기', 20)` · `search_utterances('의대정원', 20)` — 시그니처는 함수 COMMENT(`\df+`)에.
- **법제처/현행법 bridge:** 이 DB는 숫자 법령ID를 제공하지 않는다. `bill_final_outcomes.bill_no -> bills.bill_no`로 공포 이력을 붙이고, `prom_no`(공포 1,365건 100% 채움 — 가장 신뢰 가능한 bridge 키)·`promulgation_dt`·`govt_transfer_dt`·`plenary_dt`를 후속 법령 조회의 목적 중립 bridge로 넘긴다. **`prom_law_nm`(공포 법률명)은 단독 키로 쓰지 말 것** — 공포 66건이 이름 NULL이고 이름 있는 것의 절반이 공백 제거형이라 법제처(공백 사용)와 exact-match가 안 된다(누락 분포·권장 매칭은 `prom_law_nm` COMMENT). 이름으로 매칭해야 하면 양쪽에서 공백을 지우고(`replace(x,' ','')`) **중점도 통일하라** — 가운뎃점이 U+00B7(`·`, 95건)과 U+318D(`ㆍ`, 16건)로 혼재해 공백만 지워선 코드포인트가 달라 exact-match가 깨진다(`translate(x, chr(12685), chr(183))`로 U+318D→U+00B7 통일). 현행법 본문·시행일자 확정은 법제처/외부 법령 데이터 소스에서 해야 한다.

---

## 1. Cross-table 레시피

### Q1. 한 법안의 생애주기 한 장으로 보기
`bills`는 발의·위원회·본회의 처리 상태의 중심이고, 공포는 `bill_final_outcomes`, 원안→대안은 `bill_lineage`, 표결·회의는 각 junction에서 붙인다.

```sql
WITH target AS (
    SELECT bill_id
    FROM bills
    WHERE bill_no = '2218526'
)
SELECT
    b.bill_no,
    b.bill_name,
    c.committee_name,
    b.propose_dt,
    b.committee_dt,
    b.cmt_proc_dt,
    b.cmt_proc_result,
    b.proc_result,
    b.proc_dt,
    o.plenary_dt,
    o.govt_transfer_dt,
    o.promulgation_dt,
    o.prom_no,
    o.prom_law_nm,
    (
        SELECT jsonb_agg(m.hg_nm ORDER BY lp.order_no)
        FROM bill_lead_proposers lp
        JOIN members m USING (mona_cd)
        WHERE lp.bill_id = b.bill_id
    ) AS lead_proposers,
    (
        SELECT jsonb_agg(m.hg_nm ORDER BY cp.order_no)
        FROM bill_coproposers cp
        JOIN members m USING (mona_cd)
        WHERE cp.bill_id = b.bill_id
    ) AS coproposers,
    (
        SELECT jsonb_object_agg(result_vote_mod, vote_count)
        FROM (
            SELECT result_vote_mod, count(*) AS vote_count
            FROM votes
            WHERE bill_id = b.bill_id
            GROUP BY result_vote_mod
        ) v
    ) AS vote_summary,
    (
        SELECT count(*)
        FROM meeting_bills mb
        WHERE mb.bill_id = b.bill_id
    ) AS linked_meeting_count
FROM target t
JOIN bills b ON b.bill_id = t.bill_id
LEFT JOIN committees c ON c.committee_id = b.committee_id
LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no;
```

### Q2. 한 법안의 공포 + "통과인데 공포 없음" 판정 (bills + bill_final_outcomes)
공포일은 `bill_final_outcomes.promulgation_dt`(`bill_no`로 join, `bill_id` 아님). "통과인데 공포 outcome 없음"은 **법률안일 때만** 진짜 갭이다 — `bills`엔 비-법률 의안(결의안·감사요구안 등 약 169건)이 섞여 통과해도 not_promulgable이라, 양성 필터 `bill_name ~ '법(률)?안'`로 거른다(근거·갭 상세는 `bills.bill_name`·`bill_final_outcomes.prom_law_nm` COMMENT).
```sql
-- 한 법안 공포 이력
SELECT b.bill_no, b.bill_name,
       o.plenary_dt AS 본회의의결일, o.promulgation_dt AS 공포일, o.prom_no AS 공포번호
FROM bills b
JOIN bill_final_outcomes o ON o.bill_no = b.bill_no   -- ★ bill_no로 join
WHERE b.bill_no = '2213457';

-- 통과한 '법률안'인데 공포 outcome 없음 = pending 또는 진짜 갭 (비-법률 의안 제외)
-- 거부권후보 = 본회의 의결일이 처리일보다 늦음(재의결) → 단순 계류와 구분 (현재 미공포 59건 = 거부권후보 26 + 계류 33)
SELECT b.bill_no, b.bill_name, b.proc_dt,
       (o.plenary_dt > b.proc_dt) AS 거부권후보
FROM bills b
LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
WHERE b.proc_result IN ('원안가결','수정가결')
  AND b.bill_name ~ '법(률)?안'
  AND NOT EXISTS (SELECT 1 FROM bill_final_outcomes o2
                  WHERE o2.bill_no = b.bill_no AND o2.promulgation_dt IS NOT NULL)
ORDER BY b.proc_dt DESC NULLS LAST;   -- 현재 59건
```

### Q3. 원안→대안→공포 경로
대안반영폐기·수정안반영폐기 원안은 `bill_lineage` 뷰로 읽는다. raw `bill_relations`와 `bill_source_aliases`는 ETL/internal이고, 소비자는 alias 해소를 직접 조립하지 않는다.

```sql
SELECT
    bl.absorbed_bill_no,
    ab.bill_name AS absorbed_bill_name,
    bl.absorbed_proc_result,
    bl.relation_type,
    bl.alternative_bill_no,
    alt.bill_name AS alternative_bill_name,
    alt.proc_result AS alternative_proc_result,
    o.promulgation_dt,
    o.prom_no,
    o.prom_law_nm
FROM bill_lineage bl
JOIN bills ab ON ab.bill_id = bl.absorbed_bill_id
LEFT JOIN bills alt ON alt.bill_id = bl.alternative_bill_id
LEFT JOIN bill_final_outcomes o ON o.bill_no = bl.alternative_bill_no
WHERE bl.absorbed_bill_no = '2217510';
```

`alternative_bill_id IS NULL`이면 현재 canonical `bills` row로 해소하지 못한 accepted gap이다. 이 경우에도 원안이 대안/수정안에 흡수됐다는 사실 자체는 authoritative하다.

뷰 결과가 0행이라고 미흡수는 아니다 — 소관위에서 종료돼 `proc_result`가 NULL이고 `cmt_proc_result`만 `'대안반영폐기'`인 원안 487건은 likms `selRefBillId` 미수집으로 뷰에 없다(`bill_lineage` COMMENT의 COVERAGE). 그 경우 `bills.cmt_proc_result`를 함께 확인한다.

### Q4. 특정 의원의 발의·공동발의·표결·발언
대표발의와 공동발의는 분리해서 보거나, `role`을 붙여 union한다. 가결 법안 중 위원장 대안·정부제출은 개별 의원 대표발의가 없을 수 있으므로 “의원별 성공률”을 계산할 때는 COMMENT의 발의주체 커버리지 경고를 같이 읽는다. 이름이 같은 의원이 있으면(예: 박지원 2명, 표결수 0 vs 1595) `hg_nm` 매칭이 2행을 반환해 두 사람 데이터가 합쳐지므로, 한 명을 의도하면 `mona_cd`로 좁힌다(`members.hg_nm` COMMENT).

```sql
WITH member_ref AS (
    SELECT mona_cd
    FROM members
    WHERE hg_nm = '강대식'
)
SELECT '대표발의' AS role, b.bill_no, b.bill_name, b.proc_result, b.propose_dt
FROM member_ref mr
JOIN bill_lead_proposers lp ON lp.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = lp.bill_id
UNION ALL
SELECT '공동발의' AS role, b.bill_no, b.bill_name, b.proc_result, b.propose_dt
FROM member_ref mr
JOIN bill_coproposers cp ON cp.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = cp.bill_id
ORDER BY propose_dt DESC NULLS LAST, bill_no;

-- 본회의 표결 이력은 시점 정당 poly_nm_at_vote를 우선 사용한다.
SELECT b.bill_no, b.bill_name, v.result_vote_mod, v.poly_nm_at_vote, v.vote_date
FROM member_ref mr
JOIN votes v ON v.mona_cd = mr.mona_cd
JOIN bills b ON b.bill_id = v.bill_id
ORDER BY v.vote_date DESC;
```

### Q5. 위원회·기간별 법안 처리 현황
법안 소관은 `bills.committee_id -> committees`가 canonical하다. `meetings.comm_name`은 회의 원문명이라 직접 FK가 아니다(Q12 참고). `committee_id`는 불투명·비연속 코드(예: 보건복지위=9700341이고 9700007은 존재하지 않음)라 리터럴로 박지 말고, 안정·UNIQUE한 `committee_name`으로 거른다.

```sql
SELECT
    c.committee_name,
    b.proc_result,
    count(*) AS bill_count
FROM bills b
JOIN committees c ON c.committee_id = b.committee_id
WHERE b.proc_dt >= DATE '2026-01-01'
  AND b.proc_dt <  DATE '2026-04-01'
  AND c.committee_name = '보건복지위원회'
GROUP BY c.committee_name, b.proc_result
ORDER BY bill_count DESC, b.proc_result;
```

**위원회 ↔ 회의 두 경로(의미가 다름):** "위원회 *자체* 회의"는 `meetings.comm_name`으로(공백정규화는 Q12), "위원회 *소관 법안이 다뤄진* 모든 회의(본회의·법사위 체계자구심사 포함)"는 `bills.committee_id → meeting_bills → meetings` junction으로 잡는다 — `comm_name` 필터는 본회의(`comm_name` NULL)·타위 회의를 놓친다. junction을 집계할 땐 한 회의에 수십 법안이 걸려(fanout) `count(*)`가 법안 수를 부풀리므로 **`count(DISTINCT mb.meeting_id)`/`count(DISTINCT b.bill_id)`** 로 세야 한다.

### Q6. 표결 결과와 정당별 표결
`votes`는 본회의 표결만 담고, row grain은 `bill_id × mona_cd`다. `count(*)`는 표결 event 수가 아니라 의원-표 수다.

```sql
-- 한 법안의 표결 집계
SELECT result_vote_mod, count(*) AS vote_count
FROM votes
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2218526')
GROUP BY result_vote_mod
ORDER BY result_vote_mod;

-- 정당별 표결 분포
SELECT poly_nm_at_vote, result_vote_mod, count(*) AS vote_count
FROM votes
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2218526')
GROUP BY poly_nm_at_vote, result_vote_mod
ORDER BY poly_nm_at_vote, result_vote_mod;
```

### Q11. 회의 evidence 강도 — fanout 주의 (bill_meeting_contexts 뷰)
한 회의에 수십~수백 법안이 함께 걸리므로(평균 32, p90 75, max 756), "이 회의에서 다뤄짐"을 특정 법안의 직접 발언 증거로 단정하면 과잉주장이다. `bill_meeting_contexts` 뷰가 회의 fanout과 회의-단위 발언 통계를 한 자리에 준다.
```sql
SELECT comm_name, conf_date, linked_bill_count, utterance_count, utterances_by_role
FROM bill_meeting_contexts
WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2213457')
ORDER BY linked_bill_count DESC;
-- linked_bill_count 클수록(예: 45) 이 회의 발언을 해당 법안 직접 증거로 보기 어려움(raw count로 판단, 버킷 라벨 없음).
-- evidence_scope='meeting_level': 발언↔특정 법안 직접 귀속은 원천이 안 줌. 답에 한계를 밝힐 것.
-- 결과 0행이어도 미논의가 아님(meeting_bills 커버리지 부분적 — 그 테이블 COMMENT 참조).
```

법안과 연결된 특정 회의의 주변 발언을 읽을 때는 `meeting_id + sequence` stream으로 복원한다.

```sql
WITH bill_meetings AS (
    SELECT meeting_id
    FROM bill_meeting_contexts
    WHERE bill_id = (SELECT bill_id FROM bills WHERE bill_no = '2200846')
      AND linked_bill_count <= 20
)
SELECT u.meeting_id, m.title, m.conf_date,
       u.sequence, u.speaker_name, u.speaker_title, u.speaker_role, u.content
FROM bill_meetings bm
JOIN meetings m ON m.mnts_id = bm.meeting_id
JOIN utterances u ON u.meeting_id = bm.meeting_id
WHERE u.content ILIKE '%전세사기%'
ORDER BY m.conf_date, u.meeting_id, u.sequence
LIMIT 100;
```

### Q12. 회의 소관위 ↔ 법안 소관위 연결 (comm_name 공백정규화)
`bills.committee_id`는 `committees` dimension으로 정규화되어 있지만, `meetings`엔 committee_id가 없어 회의 소관과 법안 소관을 잇으려면 여전히 **공백 정규화**가 필요하다(특위 ~6종이 `committees.committee_name`엔 공백 포함 — 예: `12.29 여객기 참사…국정조사특별위원회` — 인데 `meetings.comm_name`은 내부 공백 없음 → 양쪽에서 공백 제거 후 비교).
```sql
SELECT mt.comm_name, c.committee_id, c.committee_name
FROM (SELECT DISTINCT comm_name FROM meetings WHERE comm_name IS NOT NULL) mt
LEFT JOIN committees c
  ON regexp_replace(c.committee_name, '\s', '', 'g') = regexp_replace(mt.comm_name, '\s', '', 'g')
ORDER BY c.committee_id NULLS LAST;
-- 38종 중 30종 매칭. committee_id NULL인 8종은 1회성 인사청문·국정조사·연금개혁 특위로
-- 법안 회부가 없는 회의-전용 — 누락 아님(이름기반 best-effort, 강제 FK 아님).
```
한 의제가 어느 소관위 경로로 움직였는지 볼 때는 문자열 group by 대신 이 매핑으로 법안·회의를 한 `committee_id`로 묶는다. 위원회 **membership**(누가 위원인지)은 이 DB에 없다(범위 밖).
