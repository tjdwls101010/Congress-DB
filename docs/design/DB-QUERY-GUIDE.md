# DB cross-table 레시피 — LLM 직접-SQL 소비자용

입법 스킬(no-SDK, [DECISIONS](DECISIONS.md) 2026-06-10)이 Congress-DB를 **read-only SQL로 직접 조회**할 때 보는 보조 레퍼런스다.

**먼저 DB를 introspect하라.** 구조(테이블·컬럼·타입·FK)는 [`db/schema.sql`](../../db/schema.sql)과 [ERD.md](ERD.md)에, **함정·어휘·커버리지 경고는 각 테이블·컬럼의 `COMMENT`에** 박혀 있어 `\d+ <table>`로 바로 보인다 — 예: "`bills.law_proc_dt`는 공포일이 아니다", "`utterances`는 LEFT JOIN(38.5% 비-의원)", "`speaker_role` '기타'에 정부측 묻힘", "`proc_result`에 '가결' 단독값 없음" 등 모든 함정이 그 컬럼 COMMENT에 있다. 도메인 정의는 [CONTEXT.md](../../CONTEXT.md).

이 문서는 그 COMMENT를 *반복하지 않는다*. introspection으로는 조립하기 어려운 **여러 테이블에 걸친 패턴**만 담는다(번호는 COMMENT가 가리키는 참조와 일치하도록 유지 — 연속 아님). 여기 실린 SQL은 `congress_ro`로 실제 실행해 검증했다.

---

## 0. 접속 & 경계 (introspect로는 안 보이는 메타)

- **계정:** `congress_ro` (SELECT/EXECUTE만, 쓰기 불가) · **pooled**. 연결 문자열은 `.env.local`의 `CONGRESS_RO_URL`. 자세히는 [DB-ACCESS.md](DB-ACCESS.md).
- **담는 것:** 22대 국회(2024-05-30~)의 **발의된 의안** · **본회의 표결** · **회의록 발언**.
- **안 담는 것:** 시행 중인 **현행법·시행령 본문**(→ 법제처 단계) · **위원회 단계 표결**(원천이 안 줌) · 정책의제 의미 레이어. → 이런 질문엔 "이 DB 범위 밖"이라고 답할 것.
- **검색은 DB 내장 함수로**(직접 trigram 짜지 말 것): `search_bills('전세사기', 20)` · `search_utterances('의대정원', 20)` — 시그니처는 함수 COMMENT(`\df+`)에.

---

## 1. Cross-table 레시피

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
SELECT b.bill_no, b.bill_name, b.proc_dt
FROM bills b
WHERE b.proc_result IN ('원안가결','수정가결')
  AND b.bill_name ~ '법(률)?안'
  AND NOT EXISTS (SELECT 1 FROM bill_final_outcomes o
                  WHERE o.bill_no = b.bill_no AND o.promulgation_dt IS NOT NULL)
ORDER BY b.proc_dt DESC NULLS LAST;   -- 현재 59건
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

### Q12. 회의 소관위 ↔ 법안 소관위 연결 (comm_name 공백정규화)
`bills.committee_id`는 `committees` dimension으로 정규화되어 있지만, `meetings`엔 committee_id가 없어 회의 소관과 법안 소관을 잇으려면 여전히 **공백 정규화**가 필요하다(`12.29 여객기…` vs `12.29여객기…` 공백변형 중복).
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
