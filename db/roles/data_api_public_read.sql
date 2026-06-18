-- data_api_public_read.sql — Neon Data API 공개 읽기전용 정책
--
-- 모델(DECISIONS 2026-06-18): 쓰기는 owner(congress_owner)만, 읽기는 모두에게 무인증 공개.
-- Neon Data API(PostgREST)는 congress_ro가 아니라 Neon이 만든 anonymous(무인증)·authenticated(JWT)
-- 역할로 동작한다. Neon은 Data API/Auth 프로비저닝 시 authenticated에 *전권*(arwd)을 현재·미래 테이블
-- 모두에 자동 부여(default privilege)하고, 이 프로젝트는 RLS를 끈 상태(027)라 — 잠그지 않으면 JWT를
-- 얻은 누구나 데이터를 수정/삭제하고 내부 ops/raw 테이블까지 읽을 수 있다.
--
-- 이 파일은 그 위험을 제거하고, anonymous/authenticated를 congress_ro와 동일한 읽기 allowlist(12객체
-- + 검색함수 3개)로 한정한다. anonymous에 SELECT를 줘 *무인증* 공개 읽기를 가능케 한다.
-- (단, no-token 요청이 anonymous로 매핑되려면 Neon Console의 Data API "anonymous access"가 켜져 있어야 함.)
--
-- 적용: OWNER(congress_owner) 연결로 실행. 멱등. anonymous/authenticated 역할이 없는 환경(로컬 docker)에서는 자동 skip.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anonymous')
       OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        RAISE NOTICE 'Data API 역할(anonymous/authenticated) 없음 — Neon 외 환경, skip';
        RETURN;
    END IF;

    -- 1) 위험한 default privilege 제거 (미래 테이블/함수/시퀀스가 Data API 역할에 자동 grant되지 않도록).
    --    congress_owner가 소유한 default ACL을 대상으로 회수한다.
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE congress_owner IN SCHEMA public REVOKE ALL ON TABLES FROM authenticated, anonymous';
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE congress_owner IN SCHEMA public REVOKE ALL ON SEQUENCES FROM authenticated, anonymous';
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE congress_owner IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM authenticated, anonymous';

    -- 2) 현재 모든 테이블/시퀀스/함수 권한 전면 회수(쓰기·내부테이블 노출 제거 → 깨끗한 baseline).
    EXECUTE 'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM authenticated, anonymous';
    EXECUTE 'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM authenticated, anonymous';
    EXECUTE 'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM authenticated, anonymous';

    -- 3) 스키마 USAGE(읽기 위해 필요).
    EXECUTE 'GRANT USAGE ON SCHEMA public TO anonymous, authenticated';

    -- 4) 읽기 allowlist — congress_ro와 동일한 12개 소비자 객체만. anonymous=무인증 공개 읽기.
    EXECUTE 'GRANT SELECT ON
        members, committees, bills, bill_lead_proposers, bill_coproposers,
        votes, meetings, utterances, meeting_bills, bill_final_outcomes,
        bill_lineage, bill_meeting_contexts
      TO anonymous, authenticated';

    -- 5) 검색 함수 EXECUTE(직접연결 소비자와 동일 표면).
    EXECUTE 'GRANT EXECUTE ON FUNCTION search_snippet(text, text, integer) TO anonymous, authenticated';
    EXECUTE 'GRANT EXECUTE ON FUNCTION search_bills(text, integer) TO anonymous, authenticated';
    EXECUTE 'GRANT EXECUTE ON FUNCTION search_utterances(text, integer) TO anonymous, authenticated';
END
$$;
