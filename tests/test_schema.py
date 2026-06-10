"""Slice 1 RGR 2 — 테이블 존재 검증.

`make db-migrate`로 schema.sql 적용 후 information_schema에서 테이블이 모두
존재하는지 확인한다. 컬럼/제약 검증은 RGR 3에서 별도 테스트.
"""

from congress_db.core.db import get_conn

# ERD.md에 정의된 9개 핵심 + 1개 alias + 1개 outcome + 1개 audit + 1개 카탈로그 + 3개 수집 운영 테이블.
EXPECTED_TABLES = frozenset(
    {
        "members",
        "bills",
        "bill_relations",
        "bill_source_aliases",
        "bill_final_outcomes",
        "bill_lead_proposers",
        "bill_coproposers",
        "votes",
        "meetings",
        "meeting_bills",
        "utterances",
        "speaker_title_role_map",
        "api_catalog",
        "ingest_runs",
        "ingest_cursors",
        "dead_letters",
    }
)

RETIRED_MEETING_COLUMNS = frozenset(
    {
        "conf_id",
        "class_name",
        "dae_num",
        "comm_code",
        "pdf_link_url",
        "vod_link_url",
        "conf_link_url",
        "source_api",
    }
)

RETIRED_BILL_COLUMNS = frozenset(
    {
        "detail_link",
        "age",
    }
)

RETIRED_MEETING_BILL_COLUMNS = frozenset(
    {
        "source",
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


def _public_columns(table: str) -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
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


def test_meetings_has_only_search_oriented_core_columns() -> None:
    """회의 source/link/upstream 컬럼은 core 스키마에 남기지 않는다."""
    columns = _public_columns("meetings")
    assert not (columns & RETIRED_MEETING_COLUMNS)
    assert {"is_temporary", "is_appendix"} <= columns


def test_members_exposes_roster_derived_incumbency() -> None:
    """현직 여부는 최신 의원 명부에서 파생된 공개 조회 컬럼이다."""
    columns = _public_columns("members")
    assert "is_incumbent" in columns


def test_bills_has_only_search_oriented_core_columns() -> None:
    """법안 상세 링크와 22대 고정 대수 컬럼은 core 스키마에 남기지 않는다."""
    columns = _public_columns("bills")
    assert not (columns & RETIRED_BILL_COLUMNS)


def test_meeting_bills_has_only_junction_columns() -> None:
    """회의-법안 junction은 관계 자체만 보존한다."""
    columns = _public_columns("meeting_bills")
    assert columns == {"meeting_id", "bill_id"}
