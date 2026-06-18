-- 026_direct_sql_support_indexes.sql — direct-SQL join/filter support
--
-- 직접 SQL 소비자는 committees -> bills, bills -> outcomes/lineage, 기간별 처리 현황을
-- 자주 엮는다. Postgres는 FK 컬럼을 자동 인덱싱하지 않으므로 FK/대표 질의 경로를 명시한다.

CREATE INDEX IF NOT EXISTS idx_bills_committee_proc_dt
    ON bills (committee_id, proc_dt DESC)
    WHERE committee_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bill_source_aliases_canonical_bill_id
    ON bill_source_aliases (canonical_bill_id)
    WHERE canonical_bill_id IS NOT NULL;

COMMENT ON TABLE bill_final_outcomes IS
  '본회의 의결 이후 정부이송·공포 이력(ALLBILL, bill_no 기준). 법제처/현행법 데이터로 넘기는 목적 중립 bridge는 prom_law_nm(공포 법률명), prom_no(공포번호), promulgation_dt(공포일), govt_transfer_dt(정부이송일), plenary_dt(본회의 의결일)이다. 시행일자와 현행법 본문은 이 DB에 없고 외부 법령 데이터 소스에서 확정해야 한다.';
COMMENT ON COLUMN bill_final_outcomes.prom_law_nm IS
  '공포 법률명. ALLBILL은 숫자 법령ID나 시행일자를 주지 않으므로, 법제처/현행법 조회로 이어지는 이름 bridge 후보로 사용한다.';
COMMENT ON INDEX idx_bills_committee_proc_dt IS
  'Direct-SQL support: committee-specific bill processing queries (committee_id equality + proc_dt ordering/range) and FK lookup for bills.committee_id.';
COMMENT ON INDEX idx_bill_source_aliases_canonical_bill_id IS
  'Ops/internal FK support for bill_source_aliases.canonical_bill_id. Consumer lineage queries use bill_lineage, not this raw table.';
