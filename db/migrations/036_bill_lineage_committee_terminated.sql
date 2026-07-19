-- 036_bill_lineage_committee_terminated.sql — 소관위-종료 원안 계보 커버리지 확장 (WI2·C1)
--
-- 결정(DECISIONS 2026-07-19): "bill_lineage 0행 ≠ 미흡수" 함정의 뿌리는 소관위에서 종료돼
-- proc_result가 NULL이고 cmt_proc_result만 '대안반영폐기'/'수정안반영폐기'인 원안 약 459건이
-- 스크랩 대상에서 빠져 뷰에 없던 것이다. 표본 프로브(5/5)에서 이들의 likms 상세페이지에도
-- selRefBillId가 실재함을 확인해 스크랩 대상에 편입했다(ingest_bill_relations C1). 그런데
-- bill_lineage의 relation_type이 absorbed bill의 proc_result에서만 파생돼, 이 원안들은
-- bill_relations 행이 생겨도 relation_type이 NULL로 나온다. 그래서 proc_result가 NULL이면
-- cmt_proc_result에서 파생하도록 뷰를 갱신한다. 컬럼 집합·순서·타입 불변(CREATE OR REPLACE 허용).

CREATE OR REPLACE VIEW bill_lineage AS
SELECT
    br.absorbed_bill_id,
    ab.bill_no                          AS absorbed_bill_no,
    ab.proc_result                      AS absorbed_proc_result,
    COALESCE(d.bill_id, ca.bill_id)     AS alternative_bill_id,
    COALESCE(d.bill_no, ca.bill_no)     AS alternative_bill_no,
    CASE
        WHEN ab.proc_result = '대안반영폐기'   THEN '대안반영'
        WHEN ab.proc_result = '수정안반영폐기' THEN '수정안반영'
        WHEN ab.proc_result IS NULL AND ab.cmt_proc_result = '대안반영폐기'   THEN '대안반영'
        WHEN ab.proc_result IS NULL AND ab.cmt_proc_result = '수정안반영폐기' THEN '수정안반영'
    END                                 AS relation_type
FROM bill_relations br
JOIN bills ab        ON ab.bill_id        = br.absorbed_bill_id
LEFT JOIN bills d    ON d.bill_id         = br.alternative_bill_id           -- 직접 해소
LEFT JOIN bill_source_aliases a ON a.source_bill_id = br.alternative_bill_id -- alias 경유
LEFT JOIN bills ca   ON ca.bill_id        = a.canonical_bill_id;

COMMENT ON VIEW bill_lineage IS
  '폐기 원안 → 흡수한 canonical 대안 계보(1행=1 폐기원안). alternative_bill_id/no는 직접 매칭 우선, 실패 시 bill_source_aliases 경유 해소를 내부 캡슐화(raw 두 테이블은 ops-internal·소비자 비노출). 미해소면 alternative_bill_id=NULL(대안이 bills에 부재 — 주로 수정안반영폐기). relation_type은 본회의 proc_result에서 파생하되, 소관위-종료 원안(proc_result NULL·cmt_proc_result 폐기, C1)은 cmt_proc_result에서 파생한다 — 이 경우 absorbed_proc_result가 NULL이니 처리단계는 cmt_proc_result로 읽는다. 원안→대안 traversal은 이 뷰만 쓰면 됨. **COVERAGE:** 본회의·소관위-종료 폐기 원안을 모두 selRefBillId 스크랩 대상에 넣으므로, 뷰에 0행이면 대체로 진짜 미흡수다. 잔여 갭은 likms 상세페이지에 selRefBillId가 부재한 소수뿐(부재 건수는 DECISIONS 기록).';

-- CREATE OR REPLACE는 기존 GRANT를 보존하지만 멱등 재적용(role-guard).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'congress_ro') THEN
        GRANT SELECT ON bill_lineage TO congress_ro;
    END IF;
END $$;
