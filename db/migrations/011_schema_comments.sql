-- 011_schema_comments.sql — LLM 소비층(self-description)
--
-- 목적: no-SDK 결정(DECISIONS 2026-06-10)의 직접-SQL 소비자(입법 스킬)가 congress_ro로 붙어
-- 스키마를 introspect할 때, 컬럼/테이블/함수에 '함정 경고'가 *바로 그 자리*에 보이게 한다.
-- 데이터는 충분하나 스키마가 자기설명을 못 해서 LLM이 'law_proc_dt를 공포일로 쓰는' 류의
-- 그럴듯한 오류를 짜는 문제를 구조적으로 막는다(감사 2026-06-11). 멱등(COMMENT ... IS는 덮어씀).
-- 풍부한 join 레시피·어휘표·커버리지 주의·canonical 쿼리는 docs/design/DB-QUERY-GUIDE.md 참조.

-- ============================ Tables ============================
COMMENT ON TABLE members IS
  '국회의원 인적사항(22대). PK mona_cd. 떠난 의원도 행 유지(is_incumbent=false, 삭제 안 함). 명부 동기화 전 떠난 의원은 poly_nm이 NULL일 수 있으니 시점 정당은 votes.poly_nm_at_vote를 쓸 것.';
COMMENT ON TABLE bills IS
  '국회에 *발의된* 의안(법률안 등). 시행 중인 현행법 본문이 아님(현행법은 법제처 소관, 이 DB 경계 밖). PK bill_id는 source마다 갈릴 수 있어 cross-source 영구키로 쓰지 말 것 — 안정키는 bill_no.';
COMMENT ON TABLE bill_relations IS
  '대안반영/수정안반영으로 폐기된 원안(absorbed_bill_id)과 내용을 흡수한 대안·수정안(alternative_bill_id)의 연결. alternative_bill_id는 likms source key라 bills.bill_id로 직접 join이 안 될 수 있음 → bill_source_aliases 경유.';
COMMENT ON TABLE bill_source_aliases IS
  'source별 BILL_ID를 안정키 bill_no를 경유해 canonical bills row로 잇는 정규화. canonical_bill_id가 NULL이면 해소 불가 gap.';
COMMENT ON TABLE bill_final_outcomes IS
  '본회의 의결 이후 정부이송·공포 이력(ALLBILL, bill_no 기준). 공포일은 여기 promulgation_dt. bills.law_proc_dt(법사위 처리일)를 공포일로 쓰지 말 것.';
COMMENT ON TABLE bill_lead_proposers IS
  '대표발의 N:M(bill_id×mona_cd). 발의자 정확 조회는 bills의 free-text(proposer 등) 대신 이 테이블 join.';
COMMENT ON TABLE bill_coproposers IS
  '공동발의 N:M(bill_id×mona_cd).';
COMMENT ON TABLE votes IS
  '본회의 표결, 의원 1명당 1행(법안당 약 297행). 위원회 단계 표결은 원천이 제공하지 않아 데이터에 아예 없음. count(*)는 표결 횟수가 아니라 의원-표 수 — 표결된 법안 수는 count(DISTINCT bill_id).';
COMMENT ON TABLE utterances IS
  '회의록 발언 stream(meeting_id+sequence 순). speaker_mona_cd는 비-의원 화자(장관·차관·증인·참고인·전문위원 등)에서 NULL이며 전체 발언의 38.5% — members와는 반드시 LEFT JOIN(INNER는 38.5%를 조용히 누락). 역할 필터는 speaker_role.';
COMMENT ON TABLE meetings IS
  '회의록 인스턴스(웹 HTML 목록 기준). PK mnts_id. comm_name은 본회의에서 NULL 가능.';
COMMENT ON TABLE meeting_bills IS
  '회의↔법안 N:M. 커버리지가 부분적(법안 약 85%·회의 약 59%만 연결) — 결과가 비어도 논의되지 않음을 뜻하지 않음(미연결일 수 있음). 답에 이 한계를 밝힐 것.';
COMMENT ON TABLE ingest_runs IS '운영용 수집 실행 기록. 스킬 조회 대상 아님.';
COMMENT ON TABLE ingest_cursors IS '운영용 source별 증분 기준점. 스킬 조회 대상 아님.';
COMMENT ON TABLE dead_letters IS
  '운영용 실패 item 보존. 미적재 갭의 일부만 여기 있고 accepted-gap(원천이 안 주는 값)은 없음 → 결측 판단의 단일 근거로 쓰지 말 것.';

-- ============================ bills 컬럼 (함정 집중) ============================
COMMENT ON COLUMN bills.bill_id IS
  'PK. source마다 같은 의안에 다른 값을 줄 수 있어 cross-source 키로 쓰면 안 됨. 안정키는 bill_no.';
COMMENT ON COLUMN bills.bill_no IS
  'source 간 안정 의안번호(7자리). likms/ALLBILL 조회·alias·bill_final_outcomes join의 기준 키.';
COMMENT ON COLUMN bills.proc_result IS
  '본회의 처리결과. 실제 값: 원안가결·수정가결·대안반영폐기·수정안반영폐기·철회·폐기·부결. ''가결'' 단독값은 없으니 통과는 IN (''원안가결'',''수정가결'')로 거를 것. NULL은 미처리(전체의 약 70%)이지 부결이 아님.';
COMMENT ON COLUMN bills.law_proc_dt IS
  '법사위(법제사법위) 처리일 — 공포일이 아님(검증: 520/520건이 공포일과 다르며 모두 더 이른 날짜). 공포일이 필요하면 bill_final_outcomes.promulgation_dt.';
COMMENT ON COLUMN bills.summary IS
  '주요내용. 233건은 원천 미제공으로 NULL(accepted-gap) — summary 키워드 검색은 이만큼을 조용히 누락함.';
COMMENT ON COLUMN bills.proposer IS
  '제안자 원문 텍스트. 정확한 대표/공동 발의자는 bill_lead_proposers·bill_coproposers join으로 얻을 것.';
COMMENT ON COLUMN bills.propose_dt IS '발의일.';
COMMENT ON COLUMN bills.proc_dt IS '본회의 처리일.';
COMMENT ON COLUMN bills.committee_dt IS '소관위 회부일.';
COMMENT ON COLUMN bills.cmt_proc_dt IS '소관위 처리일.';

-- ============================ members 컬럼 ============================
COMMENT ON COLUMN members.poly_nm IS
  '현재 정당. 명부 동기화 전 떠난 의원은 NULL일 수 있음 → 시점 정당은 votes.poly_nm_at_vote(떠난 의원 20명 전원 이 경로로 복구 가능).';
COMMENT ON COLUMN members.is_incumbent IS
  '현직 여부(최신 의원 명부 등장에서 파생). false는 떠남(사퇴·상실 등)이지 무효 행이 아님 — 22대 관련 전체 행적을 보려면 이 컬럼으로 거르지 말 것.';

-- ============================ votes 컬럼 ============================
COMMENT ON COLUMN votes.result_vote_mod IS
  '표결값: 찬성·반대·기권·불참. 불참이 약 25%이므로 찬성률 계산 시 분모 정의에 주의.';
COMMENT ON COLUMN votes.poly_nm_at_vote IS
  '표결 시점 정당(시점 박힘). members.poly_nm이 NULL인 떠난 의원의 정당 복구 경로 — 이 값을 members.poly_nm로 덮지 말 것.';

-- ============================ utterances 컬럼 ============================
COMMENT ON COLUMN utterances.speaker_mona_cd IS
  '의원 매핑 FK(nullable). 비-의원 화자(장관·차관·증인·참고인·전문위원 등)는 NULL이며 전체 발언의 38.5% — members join은 반드시 LEFT JOIN.';
COMMENT ON COLUMN utterances.speaker_role IS
  '발언자 역할 enum(의원·국무위원(장관)·차관·증인·참고인·전문위원·기타). 주의: ''기타''에 청장·○○위원장·지자체장·법원행정처·한국은행총재·각종 후보자 등 비-장관/차관 정부측 인사도 섞임 → 정부측 발언을 (국무위원,차관)만으로 거르면 누락. 정부기관장 단위 조회는 speaker_title 화이트리스트 필요.';

-- ============================ bill_relations / outcomes 컬럼 ============================
COMMENT ON COLUMN bill_relations.alternative_bill_id IS
  'likms selRefBillId(source key). bills.bill_id로 직접 join 시 일부(169/3715)가 실패 → bill_source_aliases.source_bill_id로 canonical 해소(130건 복구, 39건은 gap).';
COMMENT ON COLUMN bill_final_outcomes.promulgation_dt IS
  '공포일(법이 시행 근거를 갖춘 날에 해당). bills.law_proc_dt와 혼동 금지.';
COMMENT ON COLUMN bill_final_outcomes.plenary_dt IS '본회의 의결일(원천 RGS_RSLN_DT).';
COMMENT ON COLUMN bill_final_outcomes.prom_law_nm IS
  '공포 법률명. ALLBILL은 숫자 법령ID를 주지 않음(현행법 본문은 법제처 단계로 이어지는 bridge).';

-- ============================ Functions ============================
COMMENT ON FUNCTION search_bills(text, integer) IS
  'bill_name+summary trigram 유사도 검색. RETURNS (bill_id,bill_no,bill_name,propose_dt,snippet,similarity_score) 유사도 내림차순. 예: SELECT * FROM search_bills(''전세사기'', 20);';
COMMENT ON FUNCTION search_utterances(text, integer) IS
  '발언 content trigram 검색. RETURNS (utterance_id,meeting_id,sequence,speaker_name,speaker_title,snippet,similarity_score). 예: SELECT * FROM search_utterances(''의대정원'', 20);';
COMMENT ON FUNCTION search_snippet(text, text, integer) IS
  '본문에서 query 매치 주변 ±radius자(기본 80)를 발췌해 반환. search_bills/search_utterances가 내부적으로 사용.';
