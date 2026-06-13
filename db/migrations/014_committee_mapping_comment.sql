-- 014_committee_mapping_comment.sql — 회의 소관위 ↔ 법안 소관위 매핑 inform 레이어 (#94)
--
-- 2026-06-13 #120에서 bill-side committee_id는 committees dimension으로 materialize한다.
-- 이 migration은 그 이전/이후 모두에서 meetings.comm_name이 meeting-side 자유문자이며
-- bills.committee_id와 직접 FK가 아니라는 경고를 유지한다.
--
-- 실데이터 근거(congress_ro, 2026-06-12): meetings.comm_name 38종 · bill-side committee pair 31종.
-- 공백 제거 정규화 JOIN으로 30/38 매칭(공백 그대로 정확매칭은 24/38). 못 맞는 8종은 1회성
-- 인사청문·국정조사·연금개혁 특위(법안 회부 없는 회의-전용). 멱등(COMMENT ... IS는 덮어씀).

COMMENT ON COLUMN meetings.comm_name IS
  '회의 소관 위원회명(자유문자 38종). committee_id 컬럼 없음 — bill-side committees dimension과 직접 FK가 아니다. 법안 소관과 잇으려면 이름/공백 정규화 또는 별도 alias 설계가 필요하다.';
