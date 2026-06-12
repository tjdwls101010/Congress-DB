-- 016_drop_unused_ops_tables.sql — 미사용 ops/audit 테이블 물리 삭제 (심층 감사 2026-06-12)
--
-- 015에서 REVOKE로 소비자에게 숨긴 5 ops 테이블 중, *파이프라인 의존이 없는* 둘만 물리 삭제한다
-- (PM 결정 2026-06-12: 저장 절감은 미미하나 깔끔함 위해). 나머지 셋(ingest_runs·ingest_cursors·
-- dead_letters)은 22대 증분 수집·재시도 안전망이라 유지.
--  · api_catalog: core/endpoints.py PIPELINE_ENDPOINTS 상수의 DB 거울(11행)일 뿐 — 렌더러는 상수를 직접 읽도록 재지정, 테이블 쓰던 seed/verify는 제거. FK 없음.
--  · speaker_title_role_map: utterances GROUP BY로 100% 도출(3,124행, 0 불일치) — 백필이 더는 영속화하지 않음. FK 없음·뷰 의존 없음.
-- 멱등(DROP TABLE IF EXISTS). 둘 다 소비자 미조회.

DROP TABLE IF EXISTS api_catalog;
DROP TABLE IF EXISTS speaker_title_role_map;
