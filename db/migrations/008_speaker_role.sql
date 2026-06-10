-- Normalize utterance speaker titles into a small role enum.
-- Existing hosted DBs already have utterance rows, so this migration only adds
-- nullable storage and indexes. The backfill command applies NOT NULL/CHECK
-- after every existing row has a Python-classified speaker_role.

ALTER TABLE IF EXISTS utterances
    ADD COLUMN IF NOT EXISTS speaker_role TEXT;

CREATE TABLE IF NOT EXISTS speaker_title_role_map (
    speaker_title   TEXT PRIMARY KEY,
    speaker_role    TEXT NOT NULL
                    CHECK (speaker_role IN (
                        '의원', '국무위원(장관)', '차관',
                        '증인', '참고인', '전문위원', '기타'
                    )),
    n_utterances    BIGINT NOT NULL DEFAULT 0 CHECK (n_utterances >= 0),
    n_no_mona       BIGINT NOT NULL DEFAULT 0 CHECK (n_no_mona >= 0),
    n_mona          BIGINT NOT NULL DEFAULT 0 CHECK (n_mona >= 0),
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (n_utterances = n_no_mona + n_mona)
);

CREATE INDEX IF NOT EXISTS idx_utterances_role_meeting_sequence
    ON utterances (speaker_role, meeting_id, sequence);
