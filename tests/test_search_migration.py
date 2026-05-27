"""Search index migration contract."""

from congress_db.db import get_conn


def test_pg_trgm_extension_is_enabled() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        assert cur.fetchone() == (True,)


def test_search_indexes_exist() -> None:
    expected = {
        "idx_bills_bill_name_trgm",
        "idx_bills_summary_trgm",
        "idx_utterances_content_trgm",
        "idx_sg_respondents_gin",
    }
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = ANY(%s)
            """,
            (list(expected),),
        )
        found = {row[0] for row in cur.fetchall()}

    assert found == expected
