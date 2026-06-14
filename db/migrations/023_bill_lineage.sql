-- 023_bill_lineage.sql — 소비자 계보 표면 정리 (#125)
--
-- 결정(DECISIONS 2026-06-14): 소비자(입법전문가 스킬)가 폐기 원안→흡수 canonical 대안 계보를
-- 보려면 raw bill_relations + bill_source_aliases를 직접 alias-join해야 했다(구 DB-QUERY-GUIDE Q9).
-- 해소는 ETL이 이미 전부 수행(ingest_bill_relations→bill_source_aliases)하므로, 최종 canonical을
-- 단일 뷰 bill_lineage로 노출하고 raw 두 테이블은 소비자 introspection에서 숨긴다(REVOKE; 물리 보존,
-- ETL/ops 전용). relation_type은 absorbed bill의 proc_result에서 1:1 도출이라 뷰가 파생 노출하고
-- 물리 컬럼은 KEEP한다(REVOKE가 이미 소비자 노출을 제거 → 물리 DROP의 소비자 이득 0, 컬럼은 ETL이
-- 사용 중이라 DROP은 순부담; DECISIONS 2026-06-14 정정).
--
-- 라이브 검증(congress_ro, 2026-06-14): bill_relations 3,715행 = 직접해소 3,546 + alias경유 130
-- = 해소 3,676(대안반영 전부) + 미해소 39(수정안반영 전부, 대안이 bills에 없음). alias fan-out 0
-- → 뷰는 bill_relations당 정확히 1행(3,715). relation_type 도출 어긋남 0/3,715. 멱등.

-- ============================ 1. VIEW — 소비자 단일 계보 인터페이스 ============================
CREATE OR REPLACE VIEW bill_lineage AS
SELECT
    br.absorbed_bill_id,
    ab.bill_no                          AS absorbed_bill_no,
    ab.proc_result                      AS absorbed_proc_result,
    COALESCE(d.bill_id, ca.bill_id)     AS alternative_bill_id,
    COALESCE(d.bill_no, ca.bill_no)     AS alternative_bill_no,
    CASE ab.proc_result
        WHEN '대안반영폐기' THEN '대안반영'
        WHEN '수정안반영폐기' THEN '수정안반영'
    END                                 AS relation_type
FROM bill_relations br
JOIN bills ab        ON ab.bill_id        = br.absorbed_bill_id
LEFT JOIN bills d    ON d.bill_id         = br.alternative_bill_id           -- 직접 해소
LEFT JOIN bill_source_aliases a ON a.source_bill_id = br.alternative_bill_id -- alias 경유 (fan-out 0)
LEFT JOIN bills ca   ON ca.bill_id        = a.canonical_bill_id;

COMMENT ON VIEW bill_lineage IS
  '폐기 원안 → 흡수한 canonical 대안 계보(1행=1 폐기원안, 3,715행). alternative_bill_id/no는 직접 매칭 우선, 실패 시 bill_source_aliases 경유 해소를 내부 캡슐화(raw 두 테이블은 ops-internal·소비자 비노출). 미해소면 alternative_bill_id=NULL(전부 수정안반영폐기 39건 — 대안이 bills에 부재). relation_type은 absorbed_proc_result 파생: 대안반영=100% 해소, 수정안반영=100% gap. 원안→대안 traversal은 이 뷰만 쓰면 됨(구 Q9 alias-join 대체).';

-- ============================ 2. GRANT/REVOKE — 소비자 표면 교체 ============================
-- 뷰는 노출, raw 두 테이블은 introspection에서 숨김(물리 보존, ETL 전용). congress_ro는 Neon 전용 → role-guard.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'congress_ro') THEN
        GRANT SELECT ON bill_lineage TO congress_ro;
        REVOKE SELECT ON bill_relations, bill_source_aliases FROM congress_ro;
    END IF;
END $$;
