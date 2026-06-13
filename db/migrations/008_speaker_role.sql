-- Normalize utterance speaker titles into a small role enum.
-- Existing hosted DBs already have utterance rows, so this migration only adds
-- nullable storage and indexes. The backfill command applies NOT NULL/CHECK
-- after every existing row has a Python-classified speaker_role.

ALTER TABLE IF EXISTS utterances
    ADD COLUMN IF NOT EXISTS speaker_role TEXT;
