-- 029_search_perf_lifecycle_naming_comments.sql — 검색 성능 절벽·생애주기 개요·네이밍 함정 COMMENT
--
-- 결정: 2026-06-18 직접-SQL 소비자 3차 독립 재검증(ultracode, 32 에이전트, "차가운 사용자가
-- schema+COMMENT+가이드만으로 실제 어려운 질문을 끝까지 푸는지" 시뮬레이션 + EXPLAIN, 라이브 Neon).
-- 1·2차 감사(028)가 못 본 결함을 발굴: 전부 COMMENT/doc 레이어, 스키마·데이터 변경 0. 멱등.
-- 수치는 라이브(2026-06-18) 직접 재검증:
--   search_utterances('예산',20)=9,405ms Seq Scan vs ('예산안')=825ms GIN Bitmap / search_bills 2글자~0.6s vs 3글자~0.1s
--   거부권 후 재의결 = plenary_dt>proc_dt 26건(IS DISTINCT FROM은 27이나 1건은 plenary NULL=오산입)
--   sex_gbn_nm 남236/여64/NULL20(전원 is_incumbent=false) / 중점 U+00B7 95·U+318D 16
--   bill_meeting_contexts fanout 회의당 avg 32.3·p90 75·max 756(행레벨 avg 145.3) / meeting_type 인사청문회 적재 0
-- COMMENT는 last-write-wins이라 기존 검증 내용을 전부 보존하며 재기술해 병합한다.

-- 1) 검색 함수 성능 절벽 — 2글자 한국어 질의는 trigram 인덱스를 못 타 Seq Scan (must-fix)
COMMENT ON FUNCTION search_bills(query_text text, result_limit integer) IS
  'bill_name+summary 부분문자열(ILIKE) 검색, trigram 유사도로 정렬. RETURNS (bill_id,bill_no,bill_name,propose_dt,snippet,similarity_score). 예: SELECT * FROM search_bills(''전세사기'', 20). **recall 천장:** 질의 문자열이 그대로 박혀야 잡힌다(부분문자열) — 별칭(노란봉투법↔노동조합법)·동의어(저출생↔저출산)는 못 잡으니 통칭은 정식명으로 치환·질의확장 후 재질의할 것. 광역 토픽은 limit을 크게(200+). **성능:** 2글자 이하 질의는 pg_trgm이 3-gram을 못 만들어 GIN 인덱스를 못 타고 Seq Scan으로 떨어진다(2글자 ~0.6초, 3글자+는 인덱스로 ~0.1초) — 통칭은 3글자+ 정식명으로(예: 연금→연금법). 반환 행수가 result_limit과 정확히 같으면 절단됐을 수 있으니 limit을 키워 재질의. tsvector FTS로 바꾸지 말 것(한국어 형태소분석기 부재로 recall이 더 나쁨).';

COMMENT ON FUNCTION search_utterances(query_text text, result_limit integer) IS
  '발언 content 부분문자열(ILIKE) 검색, trigram 유사도로 정렬. RETURNS (utterance_id,meeting_id,sequence,speaker_name,speaker_title,snippet,similarity_score). 예: SELECT * FROM search_utterances(''의대정원'', 20). **recall 천장:** 질의 문자열이 그대로 박혀야 잡힌다 — 별칭·동의어는 못 잡으니 정식명 치환·질의확장 후 재질의. 광역 토픽은 limit 크게(200+). **성능 함정:** 2글자 이하 질의는 pg_trgm이 3-gram을 못 만들어 GIN 인덱스를 못 타고 utterances 138만행 전체 Seq Scan으로 떨어진다(2글자 ~7~9초로 소비자 statement_timeout 초과 위험; 3글자+는 인덱스로 ~0.8초) — 통칭은 3글자+ 정식명/긴 표현으로 확장(예: 예산→예산안, 의료→의료법). 반환 행수가 result_limit과 정확히 같으면 절단됐을 수 있으니 limit을 키워 재질의. tsvector FTS로 바꾸지 말 것(한국어 recall 더 나쁨).';

-- 2) 생애주기 단계 순서 개요 — 개별 컬럼 COMMENT는 정확하나 시간순 파이프라인이 한 곳에 없었음
--    (물리 컬럼 순서가 시간순과 달라 정의 순서만 읽으면 본회의가 소관위보다 앞서 보이는 오독도 동시 해소)
COMMENT ON TABLE bills IS
  '국회에 *발의된* 의안(법률안 등). 시행 중인 현행법 본문이 아님(현행법은 법제처 소관, 이 DB 경계 밖). PK bill_id는 source마다 갈릴 수 있어 cross-source 영구키로 쓰지 말 것 — 안정키는 bill_no. Direct-SQL 접근 제어는 RLS가 아니라 congress_ro GRANT allowlist가 담당한다. **생애주기 단계(시간순):** propose_dt(발의)→committee_dt(소관위 회부)→cmt_proc_dt(소관위 처리)→law_proc_dt(법사위 처리)→proc_dt(본회의 처리); 공포는 bill_final_outcomes(plenary_dt→govt_transfer_dt→promulgation_dt). 물리 컬럼 순서는 시간순이 아니다. (대안)·(정부) 법안은 committee_dt·cmt_proc_dt·law_proc_dt가 구조적 NULL(해당 컬럼 COMMENT 참조).';

-- 3) promulgation_dt 거부권 후보 수치 정정 — '다르면(27)'은 plenary NULL 1행 오산입, 정답은 '늦으면(26)'
COMMENT ON COLUMN bill_final_outcomes.promulgation_dt IS
  '공포일(법이 시행 근거를 갖춘 날). bills.law_proc_dt와 혼동 금지. **거부권 추론:** 가결인데 promulgation_dt NULL은 계류 또는 거부권 폐기다(가결 1,593 중 228건 미공포). plenary_dt가 bills.proc_dt보다 늦으면(26건) 거부권 후 재의결 후보(예: 노란봉투법·방송법·양곡관리법 — 상세는 plenary_dt COMMENT). 공포 없음 하나만으로 폐기 단정 금지.';

-- 4) bill_meeting_contexts fanout 단위(회의당) 명시 — 뷰 행 그대로 avg하면 145.3으로 보여 COMMENT가 틀린 듯 오판
COMMENT ON VIEW bill_meeting_contexts IS
  '법안×회의 evidence 컨텍스트(파생 뷰, 새 적재 없음). linked_bill_count=그 회의에 연결된 법안 수(fanout; 회의당 평균 32, p90 75, max 756 — 뷰 행을 그대로 avg하면 fanout 큰 회의가 가중돼 ~145로 보이니 회의 단위로 집계) — 클수록 이 회의 발언을 해당 법안의 직접 증거로 보기 어렵다. utterance_count·utterances_by_role는 회의 단위 집계(evidence_scope=meeting_level): 발언↔특정 법안 직접 귀속은 원천이 주지 않는다. 증거강도 버킷 라벨은 일부러 두지 않음 — raw count로 소비자가 판단(DECISIONS 2026-06-11). meeting_bills 커버리지가 부분적이라 결과가 비어도 미논의를 뜻하지 않음.';

-- 5) members.hg_nm 동명이인 식별축을 안정 컬럼으로 — 기존 '표결수 0 vs 1595'는 stub 여부일 뿐 사람 정체성 아님
COMMENT ON COLUMN members.hg_nm IS
  '표시용 한글 이름. 동명이인 존재(예: 박지원 2명 — 정당·현직은 같아도 bth_date·orig_nm(선거구)·units(선수)가 다름; 표결수 0 vs 1595는 stub 여부일 뿐 사람 정체성 아님) → 식별·join은 반드시 mona_cd로. hg_nm으로 join 금지.';

-- 6) members.sex_gbn_nm — raw 원천명 그대로 노출 + COMMENT 부재, GROUP BY 시 조용한 NULL 버킷
COMMENT ON COLUMN members.sex_gbn_nm IS
  '성별(''남''/''여''). NULL 20명=명부 동기화 전 떠난 stub 의원(is_incumbent=false, orig_nm·bth_date도 동반 NULL) — 성별 GROUP BY 시 조용한 NULL 버킷 주의.';

-- 7) meetings.meeting_type — CHECK 7종 값 목록이 introspect로 안 보였음(인사청문회는 허용되나 적재 0)
COMMENT ON COLUMN meetings.meeting_type IS
  '회의 종류(CHECK 7종: 상임위/소위원회/국정감사/특별위/본회의/국정조사/인사청문회). 인사청문회는 CHECK 허용이나 현재 적재 0건 — 실제 분포는 라이브 GROUP BY로 확인.';
