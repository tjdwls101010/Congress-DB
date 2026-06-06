-- DB-side foundation for relevance-ranked keyword search.
-- SDK/API callers can use these stable SQL functions without owning rank/snippet rules.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION search_snippet(
    source_text TEXT,
    query_text TEXT,
    radius INT DEFAULT 80
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
    WITH normalized AS (
        SELECT
            lower(source_text) AS lower_source,
            lower(query_text) AS lower_query,
            GREATEST(radius, 1) AS safe_radius
    ),
    hit AS (
        SELECT
            position(lower_query IN lower_source) AS hit_position,
            safe_radius
        FROM normalized
    )
    SELECT CASE
        WHEN btrim(query_text) = '' THEN left(source_text, safe_radius * 2)
        WHEN hit_position <= 0 THEN left(source_text, safe_radius * 2)
        ELSE substring(
            source_text
            FROM GREATEST(hit_position - safe_radius, 1)
            FOR safe_radius * 2 + char_length(query_text)
        )
    END
    FROM hit;
$$;

CREATE OR REPLACE FUNCTION search_bills(
    query_text TEXT,
    result_limit INT DEFAULT 50
)
RETURNS TABLE (
    bill_id TEXT,
    bill_no TEXT,
    bill_name TEXT,
    propose_dt DATE,
    snippet TEXT,
    similarity_score REAL
)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        b.bill_id,
        b.bill_no,
        b.bill_name,
        b.propose_dt,
        CASE
            WHEN b.summary ILIKE ('%' || btrim(query_text) || '%')
                THEN search_snippet(b.summary, btrim(query_text))
            ELSE search_snippet(b.bill_name, btrim(query_text))
        END AS snippet,
        GREATEST(
            similarity(b.bill_name, btrim(query_text)),
            similarity(COALESCE(b.summary, ''), btrim(query_text))
        )::REAL AS similarity_score
    FROM bills b
    WHERE btrim(query_text) <> ''
      AND (
          b.bill_name ILIKE ('%' || btrim(query_text) || '%')
          OR b.summary ILIKE ('%' || btrim(query_text) || '%')
      )
    ORDER BY 6 DESC, b.propose_dt DESC NULLS LAST, b.bill_no
    LIMIT GREATEST(result_limit, 0);
$$;

CREATE OR REPLACE FUNCTION search_utterances(
    query_text TEXT,
    result_limit INT DEFAULT 50
)
RETURNS TABLE (
    utterance_id BIGINT,
    meeting_id INT,
    sequence INT,
    speaker_name TEXT,
    speaker_title TEXT,
    snippet TEXT,
    similarity_score REAL
)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        u.id AS utterance_id,
        u.meeting_id,
        u.sequence,
        u.speaker_name,
        u.speaker_title,
        search_snippet(u.content, btrim(query_text)) AS snippet,
        similarity(u.content, btrim(query_text))::REAL AS similarity_score
    FROM utterances u
    WHERE btrim(query_text) <> ''
      AND u.content ILIKE ('%' || btrim(query_text) || '%')
    ORDER BY 7 DESC, u.id
    LIMIT GREATEST(result_limit, 0);
$$;
