-- 014_committee_mapping_comment.sql — 회의 소관위 ↔ 법안 소관위 매핑 inform 레이어 (#94)
--
-- 결정(AskUserQuestion 2026-06-12, DECISIONS 2026-06-11 소비 적합성 원칙): 위원회 정체성은
-- *새 canonical 테이블로 materialize하지 않고 inform한다*. bills.committee_id(31종, 99% 채움)가
-- 이미 위원회 정체성을 해결하므로, 유일한 갭인 meetings.comm_name→committee_id 연결은 새
-- committees/committee_aliases 테이블 없이 COMMENT + DB-QUERY-GUIDE 레시피(Q12)로 알린다.
-- 대부분 공백 정규화이므로 소비자(입법 스킬 속 Claude)가 JOIN으로 그 자리에서 도출 가능하다.
--
-- 실데이터 근거(congress_ro, 2026-06-12): meetings.comm_name 38종 · bills.committee/committee_id 31종.
-- 공백 제거 정규화 JOIN으로 30/38 매칭(공백 그대로 정확매칭은 24/38). 못 맞는 8종은 1회성
-- 인사청문·국정조사·연금개혁 특위(법안 회부 없는 회의-전용). 멱등(COMMENT ... IS는 덮어씀).

COMMENT ON COLUMN meetings.comm_name IS
  '회의 소관 위원회명(자유문자 38종). committee_id 컬럼 없음 — bills.committee_id(31종, 18,161/18,361 채움)와 잇으려면 공백 정규화가 필요하다(공백변형 중복 예: "12.29 여객기…" vs "12.29여객기…"). 공백 제거 정규화 JOIN으로 30/38 매칭(공백 그대로는 24/38). 못 맞는 8종은 1회성 인사청문·국정조사·연금개혁 특위로 법안 회부가 없는 회의-전용(이름기반 best-effort, 강제 FK 아님). 매핑 레시피: DB-QUERY-GUIDE Q12.';
