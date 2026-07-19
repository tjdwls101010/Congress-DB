-- 032_silent_trap_comments_and_vote_date_kst.sql — 조용히 틀리는 함정 교정 (#128)
--
-- 결정(DECISIONS 2026-06-28): 직접-SQL 소비자(입법전문가 스킬, LLM) 관점의 5렌즈 감사가
-- "에러 없이 조용히 틀리는" 함정을 라이브에서 재현 검증했다. 적대적 검증 결과 파생 뷰·생성 boolean·
-- CHECK·alias 테이블 등 대부분의 구조적 제안은 *문서화된 함정 > drift 위험 있는 파생물*이라 기각됐고,
-- 채택된 처방은 (A) COMMENT 교정/강화 + (B) 단 하나의 안전한 생성컬럼(votes.vote_date_kst)이다.
-- 새 테이블·뷰·권한 변경 없음(생성컬럼은 기존 votes GRANT가 자동 포함). 멱등.
--
-- 다루는 함정(라이브 congress_ro/owner 2026-06-28 검증):
--  1) votes.result_vote_mod '불참'은 빠진 행이 아니라 *저장된 값* 약 1/4 — 출석/찬성률 분모 오염.
--  2) votes.vote_date(TIMESTAMPTZ)를 GMT 세션에서 ::date 하면 한국 날짜가 하루 어긋남(수천 행) +
--     DATE 컬럼과 직접 등치 조인 시 조용히 0행 → 생성컬럼 vote_date_kst(고정 +9h, IMMUTABLE) 추가.
--  3) "가결-미공포"의 약 2/3는 비-법률 의안(결의안·감사요구안 등)이라 원래 공포 대상 아님 → 계류/거부권 과대.
--  4) (대안)·(정부) 법안의 구조적 NULL 타임라인, proc_result NULL=미처리 — 강화/상대표현화.
--  5) 검색: 가운뎃점(·/ㆍ) 변형·정식명 정밀도·summary-only 절단 경고를 함수 COMMENT에 추가.
--  6) 031로 사라진 객체를 가리키던 stale COMMENT 2건 + 소비자 비노출(ETL) 테이블의 유혹성 COMMENT.
--  7) 적재로 낡은 절대수치(가결 1,593→1,625 등)를 상대표현으로 — quote 시 '확인된 거짓' 방지.
--
-- 표시 정책: 휘발성 절대수치는 빼고 "정확치는 count로 재산출"로 안내(상대표현). test_schema.py의
-- gotcha marker(거부권·대안·공포일이 아님·3-gram 등)는 보존한다.

-- ============================ 1. votes.vote_date_kst — 한국 달력일 생성컬럼 ============================
-- 고정 +9h 오프셋(timezone(interval,timestamptz)는 IMMUTABLE)이라 생성컬럼이 PG16/17 모두에서 허용되고,
-- 'Asia/Seoul'과 라이브 전 구간 불일치 0(한국은 적재 범위에서 DST 없음). NOT NULL인 vote_date에서 파생.
ALTER TABLE votes
    ADD COLUMN IF NOT EXISTS vote_date_kst date
    GENERATED ALWAYS AS ((vote_date AT TIME ZONE INTERVAL '9 hours')::date) STORED;

COMMENT ON COLUMN votes.vote_date_kst IS
  '본회의 표결의 한국(KST, UTC+9) 달력일 — vote_date(timestamptz)를 고정 +9h 오프셋으로 환산한 생성컬럼(STORED, 엔진 계산이라 base와 drift 불가). **일(日) 단위 비교·조인은 반드시 이 컬럼으로** 한다: 서버 세션이 GMT라 vote_date::date는 늦은 UTC 시간대 표결을 하루 어긋나게 추출한다. DATE인 bills.proc_dt·bill_final_outcomes.plenary_dt와의 같은-날 매칭도 이 컬럼을 쓸 것(vote_date와 직접 등치 비교 금지 — TIMESTAMPTZ vs DATE라 조용히 0행).';

-- ============================ 2. votes — 불참/날짜 함정 ============================
COMMENT ON COLUMN votes.result_vote_mod IS
  '표결값 4종: 찬성·반대·기권·불참. **''불참''은 부재(빠진 행)가 아니라 명시적으로 저장된 값이며 전체의 약 1/4로 비중이 크다**(정확치는 count로 재산출). 어떤 의안에 (bill_id,mona_cd) 행이 없는 의원은 그 표결 명부(약 285~300명)에 없던 것이지 ''불참''이 아니다. ⇒ 출석·찬성률의 분모는 count(*) FILTER (WHERE result_vote_mod <> ''불참'')(출석)로 잡을 것 — 전체 행으로 나누면 불참이 섞여 찬성률이 수 %p 낮게 조용히 틀린다. **생존편향:** votes는 본회의 표결까지 간 법안만 담고 그 대부분이 가결이라(반대·기권은 극소) 부결·계류 법안의 반대표는 없다 — 찬반 대립 분석 시 이 편향을 밝힐 것.';

COMMENT ON COLUMN votes.vote_date IS
  '본회의 표결 일시(TIMESTAMPTZ). 의미상 bill-단위(같은 법안 모든 의원행이 같은 표결 순간 공유). 행간 ±1~2초는 정렬용 인공 jitter니 초단위 비교 금지. **날짜 함정:** 서버 세션 타임존이 GMT라 vote_date::date로 한국 날짜를 뽑으면 늦은 UTC 표결이 하루 어긋난다 — 일(日) 단위 비교·조인은 생성컬럼 vote_date_kst(KST 달력일)를 쓸 것. DATE인 bills.proc_dt·plenary_dt와 vote_date를 직접 등치 비교하면 타입이 달라 조용히 0행.';

-- ============================ 3. bill_final_outcomes.promulgation_dt — 가결-미공포의 비-법률 오염 ============================
-- marker 보존: '거부권'
COMMENT ON COLUMN bill_final_outcomes.promulgation_dt IS
  '공포일(법이 시행 근거를 갖춘 날). bills.law_proc_dt와 혼동 금지. **거부권 추론:** 가결인데 promulgation_dt NULL은 계류 또는 거부권 폐기일 수 있다. **단 "가결-미공포"를 곧장 계류/거부권으로 세지 말 것** — 미공포 가결의 약 2/3는 결의안·감사요구안·특검수사요구안 등 *비-법률 의안*이라 애초에 공포 대상이 아니다(정상). 진짜 계류·거부권 후보는 법률안(bill_name ~ ''법(률)?안'')으로 좁힌 미공포만 본다(정확치는 count로). plenary_dt가 bills.proc_dt보다 늦으면 거부권 후 재의결 후보(예: 노란봉투법·방송법·양곡관리법 — 상세는 plenary_dt COMMENT). 공포 없음 하나만으로 폐기 단정 금지.';

-- ============================ 4. bills — 상태/타임라인 NULL 의미 강화 + 상대표현화 ============================
-- marker 보존: committee_dt='대안', law_proc_dt='공포일이 아님'
COMMENT ON COLUMN bills.proc_result IS
  '본회의 처리결과. 실제 값: 원안가결·수정가결·대안반영폐기·수정안반영폐기·철회·폐기·부결. ''가결'' 단독값은 없으니 통과는 IN (''원안가결'',''수정가결'')로 거를 것. **NULL은 미처리(전체의 약 70%)이지 부결이 아님** — NULL 처리결과 법안은 votes에 표결행이 0이다(본회의 표결까지 간 법안만 votes에 있음). 실제 ''부결''은 극소수(한 자릿수)라 "부결 건수" 분석은 무의미에 가깝다.';

COMMENT ON COLUMN bills.committee_dt IS
  '소관위 회부일. **(대안)·(정부) 법안은 원천에 회부/심사 날짜가 없어 이 컬럼이 가결 여부와 무관하게 구조적으로 전부 NULL이다**(대안은 소관위 심사에서 생성돼 회부 단계 자체가 없음; committee_dt·cmt_proc_dt·law_proc_dt 동반 NULL). 규모: 가결의 약 2/3가 이 세 날짜 100% NULL이고 공포된 법안 중에도 절반 이상이 NULL이다(정확치는 count로 — 적재로 변동). 이 날짜를 lifecycle 필수 단계로 가정해 INNER JOIN/필터하면 법이 될 가능성이 가장 높은 대안·정부 법안이 빠진다 → LEFT JOIN.';

COMMENT ON COLUMN bills.law_proc_dt IS
  '법사위(법제사법위) 처리일 — 공포일이 아님(법사위 처리일은 공포일보다 늘 이르다). 공포일이 필요하면 bill_final_outcomes.promulgation_dt. 또한 가결의 약 2/3가 NULL((대안)·(정부) 법안은 법사위 단계 날짜 없음 — 정확치는 count로) — NULL을 종료/미통과로 오해 말 것.';

COMMENT ON COLUMN bills.bill_name IS
  '의안 제목. **이름 중복 큼**(distinct 이름이 전체의 약 1/5, 평균 ~5건/이름 — 적재로 변동) — bill_name은 식별자가 아니고 *입장*도 알려주지 않는다(같은 이름이 여야 반대 방향일 수 있음, 예: 노조법). 식별·구별은 bill_no·summary·proposer로. // bills엔 법률안 외 비-법률 의안(결의안·동의안·승인안·감사요구안·규칙안·''~의 건'' 등 약 170건)이 섞여 통과해도 공포 대상이 아님(not_promulgable). 법률안만 거르려면 bill_name ~ ''법(률)?안''(오탐 0 검증) — 종류 열거는 미달. 따라서 "통과(proc_result 가결)인데 bill_final_outcomes에 공포 없음"은 *법률안일 때만* 갭(pending/결측), 비-법률이면 정상. 레시피: DB-QUERY-GUIDE Q2.';

COMMENT ON COLUMN bills.committee_id IS
  'Nullable FK to committees.committee_id. Bill-side committee/referral identity key; join committees for display name. 위원회 *membership/명부* 키가 아님(소관·회부 식별용일 뿐). 회부 위원회가 없는 의안은 NULL(대체로 미처리·철회) — 전수 집계는 committees와 LEFT JOIN(INNER JOIN은 이들을 조용히 누락).';

-- ============================ 5. search_bills / search_snippet — 검색 함정 ============================
-- marker 보존: search_bills='3-gram'
COMMENT ON FUNCTION search_bills(text, integer) IS
  'bill_name+summary 부분문자열(ILIKE) 검색, trigram 유사도로 정렬. RETURNS (bill_id,bill_no,bill_name,propose_dt,snippet,similarity_score). 예: SELECT * FROM search_bills(''전세사기'', 200). **recall 천장:** 질의 문자열이 bill_name 또는 summary에 그대로 박혀야 잡힌다(부분문자열) — 본문에 없는 별칭·동의어는 못 잡으니(예: ''김영란법''→0건; ''노란봉투법''이 1건 잡히는 건 한 법안 summary에 우연히 적혀서지 별칭이 통하는 게 아님) 통칭은 정식명으로 치환·질의확장 후 재질의할 것. **가운뎃점 변형:** bill_name에 ·(U+00B7)와 ㆍ(U+318D)가 혼재 — 질의의 중점을 translate(q, chr(12685), chr(183))로 통일하지 않으면 0건 거짓 음성. **정식명 정밀도:** 정식명을 검색해 결과가 많아 보여도 상당수는 *그 법을 summary에서 인용한 다른 법의 개정안*이고 정작 그 법 자체의 개정안은 띄어쓰기 차이로 빠질 수 있다 — 결과의 bill_name을 확인하고 공백 변형도 함께 질의할 것. **summary-only 절단:** summary에서만 매치된 건 유사도 점수가 ~0이라 정렬 하위로 밀려 limit에 먼저 잘린다 — 광역 토픽은 먼저 limit 없이 count로 규모를 보고 페이지할 것. 반환 행수가 result_limit과 정확히 같으면 절단 의심. **성능:** 2글자 이하 질의는 pg_trgm이 3-gram을 못 만들어 GIN 인덱스를 못 타고 Seq Scan으로 떨어진다(현 규모에서 수십 ms 수준, 3글자+는 인덱스) — 통칭은 3글자+ 정식명으로(예: 연금→연금법). tsvector FTS로 바꾸지 말 것(한국어 형태소분석기 부재로 recall이 더 나쁨).';

COMMENT ON FUNCTION search_snippet(text, text, integer) IS
  '본문에서 query 매치 주변 ±radius자(기본 80)를 발췌해 반환. search_bills가 내부적으로 사용.';

-- ============================ 6. 소비자 비노출(ETL) 테이블 — 유혹성 COMMENT에 권한 경고 ============================
-- bill_relations·bill_source_aliases는 congress_ro에 SELECT 미부여(023에서 REVOKE). \dt엔 보이고
-- COMMENT가 조인 레시피처럼 읽혀, introspect-first LLM이 직접 조회하다 permission denied를 맞는다.
-- 권한 경고를 앞세우고 정식 경로(bill_lineage 뷰)를 가리킨다.
COMMENT ON TABLE bill_relations IS
  '[소비자(congress_ro) 비노출 — SELECT 미부여, 직접 조회 시 permission denied. 폐기원안→대안 계보는 bill_lineage 뷰로 읽을 것(뷰가 alias 해소를 캡슐화).] 대안반영/수정안반영으로 폐기된 원안(absorbed_bill_id)과 내용을 흡수한 대안·수정안(alternative_bill_id)의 ETL-internal 연결.';

COMMENT ON COLUMN bill_relations.alternative_bill_id IS
  'likms selRefBillId(source key). **소비자 비노출 테이블의 컬럼** — 직접 조인하지 말고 계보는 bill_lineage 뷰를 쓸 것(bill_id 직접 join은 일부 실패해 bill_source_aliases 경유 해소가 필요하며, 뷰가 이를 캡슐화).';

COMMENT ON TABLE bill_source_aliases IS
  '[소비자(congress_ro) 비노출 — SELECT 미부여, 직접 조회 시 permission denied. 계보는 bill_lineage 뷰가 alias 해소를 캡슐화해 노출.] source별 BILL_ID를 안정키 bill_no를 경유해 canonical bills row로 잇는 ETL-internal 정규화. canonical_bill_id가 NULL이면 해소 불가 gap.';

-- ============================ 7. 031로 사라진 객체를 가리키던 stale COMMENT 교정 ============================
COMMENT ON COLUMN bills.cmt_proc_dt IS
  '소관위 처리일. (대안)·(정부) 법안은 원천 미제공으로 NULL이 많다(분포는 committee_dt COMMENT 참조) — 단계 누락을 미처리로 오해 말 것.';
-- (bills.committee_id의 'meetings.comm_name' 잔재는 위 4번에서 이미 제거됨;
--  search_snippet의 'search_utterances' 잔재는 위 5번에서 제거됨.)
