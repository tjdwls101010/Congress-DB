-- 027_disable_rls_for_readonly_sql_surface.sql — make congress_ro see public facts
--
-- 이 DB는 공개 국회 사실 데이터를 read-only role로 직접 SQL 조회하게 하는 구조다.
-- 접근 제어는 db/roles/congress_ro.sql의 GRANT allowlist가 담당한다.
-- Neon에서 public table RLS가 켜진 상태(정책 0개)면 congress_ro가 모든 테이블을 0행으로
-- 보므로, schema source of truth에서도 RLS 비사용을 명시한다.

ALTER TABLE IF EXISTS members DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS committees DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bills DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bill_lead_proposers DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bill_coproposers DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS votes DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS meetings DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS utterances DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS meeting_bills DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bill_final_outcomes DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bill_relations DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS bill_source_aliases DISABLE ROW LEVEL SECURITY;

COMMENT ON TABLE bills IS
  '국회에 *발의된* 의안(법률안 등). 시행 중인 현행법 본문이 아님(현행법은 법제처 소관, 이 DB 경계 밖). PK bill_id는 source마다 갈릴 수 있어 cross-source 영구키로 쓰지 말 것 — 안정키는 bill_no. Direct-SQL 접근 제어는 RLS가 아니라 congress_ro GRANT allowlist가 담당한다.';
