-- Preserve authoritative 원안→대안/수정안 absorption links scraped from likms selRefBillId.

CREATE TABLE IF NOT EXISTS bill_relations (
    absorbed_bill_id     TEXT PRIMARY KEY REFERENCES bills (bill_id) ON DELETE RESTRICT,
    alternative_bill_id  TEXT NOT NULL,
    relation_type        TEXT NOT NULL
                         CHECK (relation_type IN ('대안반영', '수정안반영')),
    source               TEXT NOT NULL DEFAULT 'likms_selrefbillid',
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bill_relations_alternative
    ON bill_relations (alternative_bill_id);

ALTER TABLE IF EXISTS bill_relations
    DROP CONSTRAINT IF EXISTS bill_relations_alternative_bill_id_fkey;
