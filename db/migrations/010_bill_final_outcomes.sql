-- Store ALLBILL final outcome facts keyed by stable BILL_NO.
-- This is intentionally separate from bills.law_proc_dt, which is not a promulgation date.

CREATE TABLE IF NOT EXISTS bill_final_outcomes (
    bill_no              TEXT PRIMARY KEY,
    plenary_dt           DATE,
    govt_transfer_dt     DATE,
    promulgation_dt      DATE,
    prom_no              TEXT,
    prom_law_nm          TEXT,
    source               TEXT NOT NULL,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
