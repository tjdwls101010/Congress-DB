-- Resolve source-specific BILL_ID values to canonical bills via stable BILL_NO.
-- bill_relations.alternative_bill_id remains the source key; no FK is added there.

CREATE TABLE IF NOT EXISTS bill_source_aliases (
    source               TEXT NOT NULL,
    source_bill_id       TEXT NOT NULL,
    bill_no              TEXT,
    canonical_bill_id    TEXT REFERENCES bills (bill_id) ON DELETE RESTRICT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_bill_id)
);
