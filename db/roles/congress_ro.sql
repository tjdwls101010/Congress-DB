-- congress_ro — 최소권한 읽기전용 role.
-- 향후 입법전문가 스킬/런타임이 Neon에 ad-hoc SQL을 돌릴 때 쓰는 계정 (no-SDK, DECISIONS 2026-06-10
-- 안전조건 #1). LLM이 소유자 권한으로 SQL을 돌리다 환각 하나로 데이터를 손상시키는 것을 구조적으로 차단한다.
--
-- 적용: OWNER(congress_owner) 연결로 실행. 멱등(role 가드 + broad 권한 회수 + allowlist 재부여).
-- 비밀번호는 이 파일에 두지 않는다 — 별도로 설정하고 congress_ro 연결 문자열은 .env.local(gitignore)에만 둔다:
--     ALTER ROLE congress_ro PASSWORD '<strong-random>';

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'congress_ro') THEN
        CREATE ROLE congress_ro LOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE congress TO congress_ro;
GRANT USAGE ON SCHEMA public TO congress_ro;

-- 이전 broad grant나 future default grant가 재실행으로 ops 테이블을 노출하지 않도록 먼저 회수한다.
REVOKE CREATE ON SCHEMA public FROM congress_ro;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM congress_ro;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM congress_ro;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM congress_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM congress_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM congress_ro;

-- Consumer allowlist: 입법전문가 스킬이 introspect/query해도 되는 표면만 노출한다.
GRANT SELECT ON
    members,
    committees,
    bills,
    bill_lead_proposers,
    bill_coproposers,
    votes,
    meetings,
    utterances,
    meeting_bills,
    bill_final_outcomes,
    bill_lineage,
    bill_meeting_contexts
TO congress_ro;

GRANT EXECUTE ON FUNCTION search_snippet(text, text, integer) TO congress_ro;
GRANT EXECUTE ON FUNCTION search_bills(text, integer) TO congress_ro;
GRANT EXECUTE ON FUNCTION search_utterances(text, integer) TO congress_ro;
