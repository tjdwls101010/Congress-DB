-- 025_gotcha_comments.sql — 현존 데이터 함정 COMMENT (#127)
--
-- 결정(DECISIONS 2026-06-14): 2026-06-14 감사가 *이미 적재된 데이터*에 박힌 함정 4종을 찾았다 —
-- 경고가 없으면 소비자가 introspect 시 자신 있게 틀린 조인/해석을 한다. 새 데이터·구조·권한 변경 0,
-- COMMENT만 추가/병합한다(소비자가 \d+ / \df+로 읽는 자리). 기존 COMMENT는 보존하며 병합. 멱등.
-- 숫자는 라이브(congress_ro, 2026-06-14) 검증: 가결 1,593 / lead 없음 1,026(위원장 768·정부 196·기타 62),
-- bill_name distinct 3,683/18,361, 공포 NULL 228, plenary≠proc_dt 27.

-- 1) 발의주체 커버리지 함정 — bill_lead_proposers만 join하면 가결의 64%를 누락
COMMENT ON TABLE bill_lead_proposers IS
  '대표발의 N:M(bill_id×mona_cd). 단일·다중 대표발의(191건, 최대 3인) 모두의 authoritative 소스. **발의주체 커버리지 함정:** 가결 법안 1,593건 중 1,026건(64%)은 여기에 lead가 없다 — 위원장 대안(768건; 원안은 bill_lineage 뷰로 역추적)·정부제출(196건; bill_name에 ''(정부)'')·기타 위원회/특위안(62건)은 개별 의원 대표발의가 아니기 때문. 따라서 발의자/정당 기반 ''성공률·통과수'' 분석은 이 셋을 별도 처리해야 하며, 이 테이블만 join하면 가결의 64%를 조용히 누락한다. 주의: 대표발의자 ~20명은 22대 명부에 없어 members에 이름만(poly_nm·units NULL) — 정당/선수 필터 시 누락될 수 있음.';

-- 2) 동명 법안 — bill_name은 식별자도 입장 표지도 아님 (+ 기존 비-법률 필터 보존)
COMMENT ON COLUMN bills.bill_name IS
  '의안 제목. **이름 중복 큼**(distinct 3,683/18,361, 평균 ~5건/이름) — bill_name은 식별자가 아니고 *입장*도 알려주지 않는다(같은 이름이 여야 반대 방향일 수 있음, 예: 노조법). 식별·구별은 bill_no·summary·proposer로. // bills엔 법률안 외 비-법률 의안(결의안·동의안·승인안·감사요구안·규칙안·''~의 건'' 등 약 169건)이 섞여 통과해도 공포 대상이 아님(not_promulgable). 법률안만 거르려면 bill_name ~ ''법(률)?안''(오탐 0 검증) — 종류 열거는 미달. 따라서 "통과(proc_result 가결)인데 bill_final_outcomes에 공포 없음"은 *법률안일 때만* [1] 갭(pending/결측), 비-법률이면 정상. 레시피: DB-QUERY-GUIDE Q2.';

-- 3) 검색 recall 천장 — ILIKE 부분문자열(기존 COMMENT의 "trigram 유사도 검색" 표현 정정: trigram은 정렬만)
COMMENT ON FUNCTION search_bills(text, integer) IS
  'bill_name+summary 부분문자열(ILIKE) 검색, trigram 유사도로 정렬. RETURNS (bill_id,bill_no,bill_name,propose_dt,snippet,similarity_score). 예: SELECT * FROM search_bills(''전세사기'', 20). **recall 천장:** 질의 문자열이 그대로 박혀야 잡힌다(부분문자열) — 별칭(노란봉투법↔노동조합법)·동의어(저출생↔저출산)는 못 잡으니 통칭은 정식명으로 치환·질의확장 후 재질의할 것. 광역 토픽은 limit을 크게(200+). tsvector FTS로 바꾸지 말 것(한국어 형태소분석기 부재로 recall이 더 나쁨).';
COMMENT ON FUNCTION search_utterances(text, integer) IS
  '발언 content 부분문자열(ILIKE) 검색, trigram 유사도로 정렬. RETURNS (utterance_id,meeting_id,sequence,speaker_name,speaker_title,snippet,similarity_score). 예: SELECT * FROM search_utterances(''의대정원'', 20). **recall 천장:** 질의 문자열이 그대로 박혀야 잡힌다 — 별칭·동의어는 못 잡으니 정식명 치환·질의확장 후 재질의. 광역 토픽은 limit 크게(200+). tsvector FTS로 바꾸지 말 것(한국어 recall 더 나쁨).';

-- 4) 거부권 추론 — 가결인데 공포 NULL = 계류 또는 거부권 폐기 (재의결은 plenary_dt COMMENT)
COMMENT ON COLUMN bill_final_outcomes.promulgation_dt IS
  '공포일(법이 시행 근거를 갖춘 날). bills.law_proc_dt와 혼동 금지. **거부권 추론:** 가결인데 promulgation_dt NULL은 계류 또는 거부권 폐기다(가결 1,593 중 228건 미공포). plenary_dt가 bills.proc_dt와 다르면(27건) 거부권 후 재의결 후보(예: 노란봉투법·방송법·양곡관리법 — 상세는 plenary_dt COMMENT). 공포 없음 하나만으로 폐기 단정 금지.';
