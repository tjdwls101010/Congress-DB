-- 035_reconsideration_vote_comments.sql — 재의결 표결 부재 함정 COMMENT (WI3, 분기 B)
--
-- 조사(2026-07-19, DECISIONS 참조): 재의결(거부권 후 재표결) 확정 사례 2건(방송법 2200851 원표결
-- 2024-12-26·재의결 2025-04-17, 상법 2208496 원표결 2025-03-13·재의결 2025-04-17)으로 원천 표결
-- API를 직접 호출한 결과 —
--   · 표결상세(nojepdqqaweusdfbi): 두 사례 모두 300행에 VOTE_DATE distinct 값이 원표결일 하나뿐.
--     같은 MONA_CD가 두 번 등장하지 않음(한 의원의 두 표결이 함께 오지 않음).
--   · 표결BILL목록(ncocpgfiaoituanbr): BILL_ID 조회 시 각 1행, 같은 BILL_ID 중복 등장 없음(PROC_DT=원표결일).
-- ⇒ 원천이 재의결 표결 이벤트를 아예 제공하지 않는다(분기 B). 저장분(원표결) = API 현재 응답이라
--   재조회해도 원표결 그대로 유지(덮임 무해) — votes 재조회 정책·grain 변경 불요. grain을 바꿔도 담을
--   데이터가 없다. 남은 조치는 "단일 이벤트 전제" COMMENT의 교정 + 재의결 함정 경고(이 마이그레이션).
--
-- 기존 vote_date COMMENT는 "같은 법안 모든 의원행이 같은 표결 순간 공유"라고 단일 이벤트를 무조건 전제해
-- 재의결 함정을 오히려 은폐했다(대칭 결함: bill_final_outcomes.plenary_dt COMMENT는 재의결을 이미 경고).
-- 구조·권한 변경 0, COMMENT만. 멱등.

COMMENT ON TABLE votes IS
  '본회의 표결, 의원 1명당 1행. 행이 있으면 본회의까지 간 의안; 없으면 미상정이거나 원천 미수집(votes만으론 구분 불가 — bills.proc_result로 교차확인). 위원회 단계 표결은 원천이 안 줘 데이터에 없음. 표결된 법안 수 = count(DISTINCT bill_id). **재의결 함정:** 대통령 거부권 후 재의결된 법안은 본회의 표결이 둘이나 원천 API가 원표결만 줘 하나만 저장된다(부재 이벤트 식별·보완은 vote_date COMMENT 참조).';

COMMENT ON COLUMN votes.vote_date IS
  '본회의 표결 일시(TIMESTAMPTZ). 한 법안당 표결 이벤트 하나만 저장하며(그 이벤트의 모든 의원행이 같은 표결 순간 공유), 저장분은 원(原)표결이다. **재의결 함정:** 대통령 거부권 후 재의결된 법안은 본회의 표결이 두 번 있으나 원천 표결 API가 원표결만 제공하고 재의결 표결은 주지 않아 여기 없다(2026-07-19 실측·DECISIONS 참조; 방송법 2200851 등 재의결 26건). 재의결 여부는 bill_final_outcomes.plenary_dt > bills.proc_dt로 식별하고, 부재한 재의결 표결의 찬반·이탈표는 회의록·websearch로 확인한다(이 DB로는 원표결 분포만 답할 수 있음). 행간 ±1~2초는 정렬용 인공 jitter니 초단위 비교 금지. **날짜 함정:** 서버 세션 타임존이 GMT라 vote_date::date로 한국 날짜를 뽑으면 늦은 UTC 표결이 하루 어긋난다 — 일(日) 단위 비교·조인은 생성컬럼 vote_date_kst(KST 달력일)를 쓸 것. DATE인 bills.proc_dt·plenary_dt와 vote_date를 직접 등치 비교하면 타입이 달라 조용히 0행.';
