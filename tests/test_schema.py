"""Slice 1 RGR 2 — 11개 테이블 존재 검증.

`make db-migrate`로 schema.sql 적용 후 information_schema에서 테이블이 모두
존재하는지 확인한다. 컬럼/제약 검증은 RGR 3에서 별도 테스트.
"""

from congress_db.db import get_conn

# ERD.md에 정의된 10개 핵심 + 1개 카탈로그 = 11개.
EXPECTED_TABLES = frozenset(
    {
        "members",
        "bills",
        "bill_lead_proposers",
        "bill_coproposers",
        "votes",
        "meetings",
        "agenda_items",
        "meeting_bills",
        "utterances",
        "session_groups",
        "api_catalog",
    }
)


def _public_tables() -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
            return {row[0] for row in cur.fetchall()}


def test_all_expected_tables_exist() -> None:
    """ERD에 정의된 테이블이 public 스키마에 모두 있다."""
    tables = _public_tables()
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables: {sorted(missing)}"


def test_no_unexpected_tables() -> None:
    """예상 외의 테이블이 끼어들지 않았다 (스키마 누수 방지)."""
    tables = _public_tables()
    extra = tables - EXPECTED_TABLES
    assert not extra, f"Unexpected tables: {sorted(extra)}"
