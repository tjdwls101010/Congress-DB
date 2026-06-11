-- congress_ro — 최소권한 읽기전용 role.
-- 향후 입법전문가 스킬/런타임이 Neon에 ad-hoc SQL을 돌릴 때 쓰는 계정 (no-SDK, DECISIONS 2026-06-10
-- 안전조건 #1). LLM이 소유자 권한으로 SQL을 돌리다 환각 하나로 데이터를 손상시키는 것을 구조적으로 차단한다.
--
-- 적용: OWNER(congress_owner) 연결로 실행. 멱등(role 가드 + GRANT는 additive).
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
GRANT SELECT ON ALL TABLES IN SCHEMA public TO congress_ro;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO congress_ro;  -- search_bills/search_utterances/search_snippet + pg_trgm

-- 향후 owner가 만드는 테이블·함수에도 자동 SELECT/EXECUTE 부여
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO congress_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO congress_ro;
