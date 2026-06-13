-- 017_drop_bills_rst_mona_cd.sql — 대표발의 정본을 bill_lead_proposers로 일원화
--
-- 2026-06-13 cleanup decision: bills.rst_mona_cd is a single-lead convenience FK.
-- It duplicates bill_lead_proposers for single-lead bills and is NULL for every
-- multi-lead bill, so it is removed from the consumer schema surface.

DROP INDEX IF EXISTS idx_bills_rst;

ALTER TABLE bills
    DROP COLUMN IF EXISTS rst_mona_cd;
