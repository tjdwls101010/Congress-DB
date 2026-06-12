-- Store BILLRCPV2 document URL inventory keyed by stable BILL_NO and document kind.
-- URL inventory only: HWP/PDF bodies are intentionally not downloaded or parsed here.

CREATE TABLE IF NOT EXISTS bill_documents (
    bill_no              TEXT NOT NULL,
    source               TEXT NOT NULL CHECK (source = 'billrcpv2'),
    source_bill_id       TEXT NOT NULL,
    document_kind        TEXT NOT NULL
                         CHECK (document_kind IN ('bill_text', 'cost_estimate')),
    hwp_url              TEXT,
    pdf_url              TEXT,
    link_url             TEXT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    parse_status         TEXT NOT NULL DEFAULT 'not_parsed'
                         CHECK (parse_status = 'not_parsed'),
    PRIMARY KEY (bill_no, document_kind)
);

COMMENT ON TABLE bill_documents IS
  '법안 문서 URL inventory(BILLRCPV2, bill_no 안정키). 원문(document_kind=''bill_text'')·비용추계서(''cost_estimate'')의 HWP/PDF URL과 상세페이지(link_url)만 담는다 — 본문은 다운로드·파싱하지 않음(parse_status 항상 ''not_parsed''). cost_estimate는 희소(대부분 bill_text만). 모든 법안에 문서가 있지는 않으니 행 없음이 문서 없음을 뜻하지 않을 수 있음. (bill_no, document_kind)당 1행.';
COMMENT ON COLUMN bill_documents.document_kind IS
  '문서 종류: bill_text(의안 원문) | cost_estimate(비용추계서). BILLRCPV2의 BOOK_*=원문, COST_*=비용추계서 매핑. 신구조문대비표·검토보고서는 직접 API가 없어 미수록.';
