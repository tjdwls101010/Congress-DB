-- 028_lifecycle_bridge_gotcha_comments.sql — 생애주기·공포 bridge 함정 COMMENT
--
-- 결정: 2026-06-18 직접-SQL 소비자 7차원 감사(ultracode, 36 에이전트, 라이브 Neon RO 교차검증)가
-- "에러 없는 조용한 오답/누락"을 만드는 함정 3종을 찾았다. 전부 COMMENT/doc 레이어이고 스키마·데이터
-- 변경 0. COMMENT는 last-write-wins이라 기존 검증 내용을 보존하며 전체를 재기술해 병합한다. 멱등.
-- 수치는 라이브(2026-06-18, congress_owner) 직접 재검증: 공포 1,365 / prom_no NULL 0 / prom_law_nm NULL 66 /
-- 이름 있는 1,299 중 공백없음 648 / 가결 1,593 / committee_dt NULL 1,026 / law_proc_dt NULL 1,066 /
-- 대안 740·정부 196 = 세 날짜 100% NULL / poly_nm NULL 20명(전원 is_incumbent=FALSE) / 공동발의 NULL 10,726행 /
-- cmt_proc_result='대안반영폐기' & proc_result NULL = 487건(bill_lineage·raw 둘 다 부재).

-- 1) 공포 → 법제처 이름 bridge 함정 (prom_law_nm 단독 사용 금지)
COMMENT ON COLUMN bill_final_outcomes.prom_law_nm IS
  '공포 법률명(raw, 저장값 변형 금지). 법제처/현행법 조회로 이어지는 이름 bridge 후보지만 *단독 사용 금지* — 두 함정: (1) 공포 1,365건 중 66건이 이름 NULL(주로 위원장 대안으로 제정된 신규법, 예: 인공지능 데이터센터 특별법 2218836·국방반도체법 2218831·간호법). (2) 이름 있는 1,299건 중 648건(~50%)이 공백 제거형이라 법제처(공백 사용)와 exact-match/equijoin이 안 됨 — 같은 법이 DB 안에서도 공백 有/無 두 형태로 공존(예: 감염병의 예방 및 관리에 관한 법률), 중점도 ㆍ(U+318D)·(U+00B7) 혼재. 권장: 공포 판정·bridge 키는 prom_no(공포 1,365건 100% 채움)를 쓰고, 이름 매칭은 양쪽 공백 제거 후 비교(replace로 스페이스 삭제), 이름 NULL이면 bills.bill_name으로 폴백. ALLBILL은 숫자 법령ID·시행일자를 주지 않으므로 현행법 본문·시행일자는 외부 법령 소스에서 확정.';

-- 2) 생애주기 단계-날짜가 (대안)·(정부) 법안에서 체계적 NULL — 법이 된 법안을 조용히 누락
COMMENT ON COLUMN bills.committee_dt IS
  '소관위 회부일. **(대안)·(정부) 법안은 원천에 회부/심사 날짜가 없어 이 컬럼이 가결 여부와 무관하게 구조적으로 전부 NULL이다**(대안은 소관위 심사에서 생성돼 회부 단계 자체가 없음; committee_dt·cmt_proc_dt·law_proc_dt 동반 NULL). 규모: 가결 1,593건 중 committee_dt 1,026건(64%) NULL이고 그중 가결된 대안 740·정부 196건은 세 날짜 100% NULL(공포된 1,365건 중에도 811건/59% NULL; 수치는 일별 갱신 snapshot). 이 날짜를 lifecycle 필수 단계로 가정해 INNER JOIN/필터하면 법이 될 가능성이 가장 높은 대안·정부 법안이 빠진다.';
COMMENT ON COLUMN bills.cmt_proc_dt IS
  '소관위 처리일. (대안)·(정부) 법안은 원천 미제공으로 NULL이 많다(분포는 committee_dt COMMENT 참조) — 단계 누락을 미처리로 오해 말 것.';
COMMENT ON COLUMN bills.law_proc_dt IS
  '법사위(법제사법위) 처리일 — 공포일이 아님(검증: 520/520건이 공포일과 다르며 모두 더 이른 날짜). 공포일이 필요하면 bill_final_outcomes.promulgation_dt. 또한 가결 1,593건 중 1,066건(67%)이 NULL((대안)·(정부) 법안은 법사위 단계 날짜 없음) — NULL을 종료/미통과로 오해 말 것.';

-- 3) 발의자 정당 집계 함정 — bill_coproposers는 그동안 무경고였음 (더 큰 노출을 가진 쪽)
COMMENT ON TABLE bill_coproposers IS
  '공동발의 N:M(bill_id×mona_cd, 206k). co와 lead는 같은 법안에서 겹치지 않음 → 총 발의자 = 두 테이블 합집합(중복 없음). 1건당 보통 8~190명(중앙값 ~10), 모든 공동법안은 대표법안 부분집합(orphan 없음). **발의자 정당 함정:** members.poly_nm으로 GROUP BY/JOIN하면 poly_nm NULL인 의원 20명(전원 is_incumbent=FALSE, 명부 동기화 전 이탈)이 NULL 버킷으로 빠진다 — 공동발의 10,726행(5.2%)·대표발의 989행 영향. 발의 시점 정당 컬럼이 없으니(poly_nm_at_propose 부재) 정당이 필요하면 그 의원의 votes.poly_nm_at_vote를 best-effort 프록시로 쓸 것(이 20명 전원 표결 이력으로 복구 가능). members.poly_nm 백필 금지(시점 정당을 덮어씀).';

-- 4) bill_lineage 커버리지 — 소관위-종료 대안반영폐기 원안 487건은 뷰에 없음
COMMENT ON VIEW bill_lineage IS
  '폐기 원안 → 흡수한 canonical 대안 계보(1행=1 폐기원안, 3,715행). alternative_bill_id/no는 직접 매칭 우선, 실패 시 bill_source_aliases 경유 해소를 내부 캡슐화(raw 두 테이블은 ops-internal·소비자 비노출). 미해소면 alternative_bill_id=NULL(전부 수정안반영폐기 39건 — 대안이 bills에 부재). relation_type은 absorbed_proc_result 파생: 대안반영=100% 해소, 수정안반영=100% gap. 원안→대안 traversal은 이 뷰만 쓰면 됨(구 Q9 alias-join 대체). **COVERAGE:** 이 뷰는 absorbed 원안의 proc_result(본회의)=대안/수정안반영폐기인 건만 담는다. 소관위에서 종료돼 proc_result는 NULL이고 cmt_proc_result만 대안반영폐기인 원안 487건은 likms selRefBillId 미수집이라 뷰·raw bill_relations 둘 다에 없음 — 결과 0행이 미흡수를 뜻하지 않으니 bills.cmt_proc_result도 함께 확인할 것.';
