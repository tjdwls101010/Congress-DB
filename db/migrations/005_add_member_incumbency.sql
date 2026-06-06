-- Track current legislators from the latest roster sync without deleting departed members.

ALTER TABLE IF EXISTS members
    ADD COLUMN IF NOT EXISTS is_incumbent BOOLEAN NOT NULL DEFAULT FALSE;
