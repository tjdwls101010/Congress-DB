-- Slice 10 search indexes.
-- Decision: use pg_trgm for first-pass Korean keyword search because it works
-- in local Postgres and Supabase without changing the runtime image.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_bills_bill_name_trgm
    ON bills USING gin (bill_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_bills_summary_trgm
    ON bills USING gin (summary gin_trgm_ops)
    WHERE summary IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_utterances_content_trgm
    ON utterances USING gin (content gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_sg_respondents_gin
    ON session_groups USING gin (respondents jsonb_path_ops);
