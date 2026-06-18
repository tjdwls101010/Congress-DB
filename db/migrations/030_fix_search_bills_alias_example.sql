-- 030_fix_search_bills_alias_example.sql — search_bills recall 예시 정정
--
-- 결정: 2026-06-18 wiki self-sufficiency cold-read 테스트(서브에이전트, wiki만 읽고 라이브 활용)가
-- search_bills COMMENT/문서의 "별칭(노란봉투법) 못 잡음" 예시가 *틀렸음*을 발견. 라이브 재검증:
-- search_bills('노란봉투법')=1건(2218912 노조법) — 이 통칭이 한 법안 summary에 그대로 적혀 있어
-- 부분문자열 검색이 잡는다. 즉 노란봉투법은 "alias 못 잡음"의 반례가 아니라 오히려 잡히는 예다.
-- search_bills는 bill_name OR summary 양쪽을 검색하므로, "alias 못 잡음"은 *본문에 그대로 없을 때*만 참.
-- 진짜 0건 별칭(예: '김영란법' 0건)으로 예시 교체. COMMENT는 last-write-wins이라 029 본문을
-- 전부 보존하며 recall 절만 정정한다(성능 경고·'3-gram' 가드 키워드 유지). 멱등.

COMMENT ON FUNCTION search_bills(query_text text, result_limit integer) IS
  'bill_name+summary 부분문자열(ILIKE) 검색, trigram 유사도로 정렬. RETURNS (bill_id,bill_no,bill_name,propose_dt,snippet,similarity_score). 예: SELECT * FROM search_bills(''전세사기'', 20). **recall 천장:** 질의 문자열이 bill_name 또는 summary에 그대로 박혀야 잡힌다(부분문자열) — 본문에 없는 별칭·동의어는 못 잡으니(예: ''김영란법''→0건; 단 ''노란봉투법''은 한 법안 summary에 적혀 있어 1건 잡힘) 통칭은 정식명으로 치환·질의확장 후 재질의할 것. 광역 토픽은 limit을 크게(200+). **성능:** 2글자 이하 질의는 pg_trgm이 3-gram을 못 만들어 GIN 인덱스를 못 타고 Seq Scan으로 떨어진다(2글자 ~0.6초, 3글자+는 인덱스로 ~0.1초) — 통칭은 3글자+ 정식명으로(예: 연금→연금법). 반환 행수가 result_limit과 정확히 같으면 절단됐을 수 있으니 limit을 키워 재질의. tsvector FTS로 바꾸지 말 것(한국어 형태소분석기 부재로 recall이 더 나쁨).';
