-- 019_drop_utterances_role_meeting_sequence_idx.sql — low-use role index cleanup
--
-- Live audit found this index was about 85 MB with very low scan count. Meeting
-- stream access remains covered by UNIQUE(meeting_id, sequence), and keyword
-- search remains covered by idx_utterances_content_trgm.

DROP INDEX IF EXISTS idx_utterances_role_meeting_sequence;
