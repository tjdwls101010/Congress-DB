-- 031_drop_meeting_minutes.sql — 회의록(회의·발언) 도메인 전면 제거
--
-- 결정(2026-06-28, DECISIONS 참조): 입법전문가 harness의 소비 관점에서 회의록 발언(utterances)은
-- DB의 압도적 비중(라이브 main 1,780MB ≈ 논리 데이터의 ~84%, 138만 행)을 차지하면서도,
-- "논의 진척"은 원래 구조화 테이블(bills.proc_result·bill_lineage·bill_final_outcomes)이 답하고
-- 발언↔법안 직접 귀속은 fanout(회의당 평균 32 법안)으로 신뢰도가 낮다. "누가 무엇을 발언했나"의
-- 심층 분석은 websearch로 대체하고, DB는 의원·법안·표결·발의·공포·계보의 1차 사실에 집중한다.
-- 회의 메타(meetings·meeting_bills)도 본문이 빠지면 본업(발언↔법안 다리)이 사라지고 회의맥락 뷰가
-- 빈 껍데기가 되므로 함께 제거한다(C안: 회의 도메인 전면 드롭).
--
-- 제거 대상: 뷰 bill_meeting_contexts, 함수 search_utterances, 테이블 utterances·meeting_bills·meetings.
-- 유지: search_snippet(제네릭 — search_bills가 사용), search_bills, bill_lineage.
-- 외부 테이블이 이 셋을 FK로 참조하지 않음(meeting_bills→meetings, utterances→meetings는 모두 드롭 집합 내부).
-- 드롭 시 해당 객체의 인덱스·소유 시퀀스·GRANT(congress_ro/anonymous/authenticated)는 자동 소멸한다.
-- (role 정본 db/roles/*.sql에서 이 객체 grant 라인은 함께 제거 — 재실행 에러 방지.)
--
-- 안전: 실행 전 Neon 스냅샷 브랜치(pre-utterances-drop-20260628)로 복원망 확보.
-- 적용: OWNER(congress_owner) 연결, psql -1(single-transaction)로 wrap. 멱등(IF EXISTS).
-- 되돌리기: 회의·발언 재적재는 ingest 파이프라인의 회의 목록·안건 단계는 싸고, 발언 본문 재스크래핑만 비싸다.

-- 1) 회의맥락 뷰 먼저 (meeting_bills·meetings·utterances 모두에 의존)
DROP VIEW IF EXISTS bill_meeting_contexts;

-- 2) 발언 검색 함수 (utterances 전용)
DROP FUNCTION IF EXISTS search_utterances(text, integer);

-- 3) 테이블 (의존 순서: utterances·meeting_bills 가 meetings 를 FK 참조 → meetings 마지막)
DROP TABLE IF EXISTS utterances;
DROP TABLE IF EXISTS meeting_bills;
DROP TABLE IF EXISTS meetings;

-- 검증(수동): 아래가 모두 0/부재여야 한다.
--   SELECT count(*) FROM information_schema.tables
--     WHERE table_schema='public' AND table_name IN ('utterances','meeting_bills','meetings');   -- 0
--   SELECT to_regclass('public.bill_meeting_contexts');                                            -- NULL
--   SELECT proname FROM pg_proc WHERE proname='search_utterances';                                 -- 0 rows
--   SELECT proname FROM pg_proc WHERE proname IN ('search_bills','search_snippet');                -- 유지 확인
