"""Search index migration contract."""

from collections.abc import Iterator

import pytest

from congress_db.core.db import get_conn

TEST_SEARCH_BILLS = ("TEST_SEARCH_BILL_1", "TEST_SEARCH_BILL_2", "TEST_SEARCH_BILL_3")


def test_pg_trgm_extension_is_enabled() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        assert cur.fetchone() == (True,)


def test_search_indexes_exist() -> None:
    expected = {
        "idx_bills_bill_name_trgm",
        "idx_bills_summary_trgm",
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


def test_search_filters_can_use_trigram_indexes() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL enable_seqscan = off")
        cur.execute(
            """
            EXPLAIN (COSTS OFF)
            SELECT bill_id
            FROM bills
            WHERE bill_name ILIKE '%테스트전세사기%'
               OR summary ILIKE '%테스트전세사기%'
            LIMIT 50
            """
        )
        bill_plan = "\n".join(row[0] for row in cur.fetchall())

    assert "idx_bills_bill_name_trgm" in bill_plan
    assert "idx_bills_summary_trgm" in bill_plan


@pytest.fixture(autouse=True)
def clean_search_rows() -> Iterator[None]:
    _delete_search_rows()
    yield
    _delete_search_rows()


def _delete_search_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_SEARCH_BILLS),))
        conn.commit()


def test_search_bills_orders_by_similarity_and_returns_snippet() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, propose_dt, summary)
            VALUES
                (
                    'TEST_SEARCH_BILL_1',
                    '9600001',
                    '테스트전세사기 피해자 지원 특별법안',
                    '2026-01-03',
                    '테스트전세사기 피해자에게 보증금 회수와 주거 안정을 지원한다.'
                ),
                (
                    'TEST_SEARCH_BILL_2',
                    '9600002',
                    '주택 임대차 분쟁 조정법안',
                    '2026-01-04',
                    '임대차 분쟁 중 테스트전세사기 관련 상담 절차를 정비한다.'
                ),
                (
                    'TEST_SEARCH_BILL_3',
                    '9600003',
                    '항공안전법 일부개정법률안',
                    '2026-01-05',
                    '항공기 안전 점검 기준을 정비한다.'
                )
            """
        )
        cur.execute(
            """
            SELECT bill_id, snippet, similarity_score
            FROM search_bills('테스트전세사기', 10)
            """
        )
        rows = cur.fetchall()
        conn.commit()

    assert [row[0] for row in rows] == ["TEST_SEARCH_BILL_1", "TEST_SEARCH_BILL_2"]
    assert "테스트전세사기" in rows[0][1]
    assert rows[0][2] >= rows[1][2]
