-- Remove derived Q&A session groups.
-- Minutes retrieval now uses utterance keyword search plus neighboring sequence reads.

DROP INDEX IF EXISTS idx_utterances_session_group;
DROP INDEX IF EXISTS idx_sg_respondents_gin;
DROP INDEX IF EXISTS idx_sg_questioner;
DROP INDEX IF EXISTS idx_sg_meeting;

ALTER TABLE IF EXISTS utterances
    DROP COLUMN IF EXISTS session_group_id;

DROP TABLE IF EXISTS session_groups;

DELETE FROM ingest_cursors
WHERE source = 'session_groups';
