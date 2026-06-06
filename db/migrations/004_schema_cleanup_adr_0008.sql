-- Finish ADR-0008 search-oriented schema cleanup before hosted Postgres migration.
-- These source/link fields are not part of the core query surface.

ALTER TABLE IF EXISTS bills
    DROP COLUMN IF EXISTS detail_link,
    DROP COLUMN IF EXISTS age;

ALTER TABLE IF EXISTS meeting_bills
    DROP COLUMN IF EXISTS source;
