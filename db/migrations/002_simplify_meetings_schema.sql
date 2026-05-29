-- Simplify meeting core schema for search-oriented Supabase migration.
-- This migration is intentionally idempotent so existing local backfill DBs
-- and fresh schema installs converge on the same pre-migration structure.

ALTER TABLE IF EXISTS meetings
    ADD COLUMN IF NOT EXISTS is_temporary BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_appendix BOOLEAN NOT NULL DEFAULT FALSE,
    DROP COLUMN IF EXISTS conf_id,
    DROP COLUMN IF EXISTS class_name,
    DROP COLUMN IF EXISTS dae_num,
    DROP COLUMN IF EXISTS comm_code,
    DROP COLUMN IF EXISTS pdf_link_url,
    DROP COLUMN IF EXISTS vod_link_url,
    DROP COLUMN IF EXISTS conf_link_url,
    DROP COLUMN IF EXISTS source_api;

DROP TABLE IF EXISTS agenda_items;
