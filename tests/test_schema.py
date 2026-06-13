"""Slice 1 RGR 2 — 테이블 존재 검증.

`make db-migrate`로 schema.sql 적용 후 information_schema에서 테이블이 모두
존재하는지 확인한다. 컬럼/제약 검증은 RGR 3에서 별도 테스트.
"""

from congress_db.core.db import get_conn

# ERD.md에 정의된 핵심/차원/alias/outcome + 3개 수집 운영 테이블.
EXPECTED_TABLES = frozenset(
    {
        "members",
        "committees",
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
        "ingest_runs",
        "ingest_cursors",
        "dead_letters",
    }
)

EXPECTED_MEMBER_COLUMNS = frozenset(
    {
        "mona_cd",
        "hg_nm",
        "hj_nm",
        "eng_nm",
        "bth_date",
        "sex_gbn_nm",
        "poly_nm",
        "orig_nm",
        "elect_gbn_nm",
        "units",
        "is_incumbent",
        "fetched_at",
    }
)

EXPECTED_MEETING_COLUMNS = frozenset(
    {
        "mnts_id",
        "title",
        "meeting_type",
        "session_no",
        "conf_date",
        "comm_name",
        "fetched_at",
    }
)

EXPECTED_BILL_COLUMNS = frozenset(
    {
        "bill_id",
        "bill_no",
        "bill_name",
        "propose_dt",
        "proposer",
        "committee_id",
        "proc_result",
        "proc_dt",
        "law_proc_dt",
        "committee_dt",
        "cmt_proc_dt",
        "cmt_proc_result",
        "summary",
        "fetched_at",
    }
)

EXPECTED_COMMITTEE_COLUMNS = frozenset(
    {
        "committee_id",
        "committee_name",
    }
)

EXPECTED_VOTE_COLUMNS = frozenset(
    {
        "bill_id",
        "mona_cd",
        "vote_date",
        "result_vote_mod",
        "poly_nm_at_vote",
    }
)

EXPECTED_BILL_RELATION_COLUMNS = frozenset(
    {
        "absorbed_bill_id",
        "alternative_bill_id",
        "relation_type",
        "fetched_at",
    }
)

EXPECTED_BILL_FINAL_OUTCOME_COLUMNS = frozenset(
    {
        "bill_no",
        "plenary_dt",
        "govt_transfer_dt",
        "promulgation_dt",
        "prom_no",
        "prom_law_nm",
        "fetched_at",
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


def _fk_columns(table: str, constraint: str) -> tuple[str, str, list[str], list[str]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.conrelid::regclass::text AS source_table,
                    c.confrelid::regclass::text AS target_table,
                    ARRAY(
                        SELECT a.attname
                        FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                        ORDER BY k.ord
                    ) AS source_columns,
                    ARRAY(
                        SELECT a.attname
                        FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = c.confrelid AND a.attnum = k.attnum
                        ORDER BY k.ord
                    ) AS target_columns
                FROM pg_constraint c
                WHERE c.conrelid = %s::regclass
                  AND c.conname = %s
                  AND c.contype = 'f'
                """,
                (f"public.{table}", constraint),
            )
            row = cur.fetchone()
            assert row is not None
            return row


def _column_comment(table: str, column: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT col_description(%s::regclass, attnum)
                FROM pg_attribute
                WHERE attrelid = %s::regclass
                  AND attname = %s
                  AND NOT attisdropped
                """,
                (f"public.{table}", f"public.{table}", column),
            )
            row = cur.fetchone()
            return row[0] if row else None


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
    assert _public_columns("meetings") == EXPECTED_MEETING_COLUMNS


def test_members_exposes_roster_derived_incumbency() -> None:
    """현직 여부는 최신 의원 명부에서 파생된 공개 조회 컬럼이다."""
    assert _public_columns("members") == EXPECTED_MEMBER_COLUMNS


def test_committees_has_only_bill_side_identity_columns() -> None:
    """위원회 dimension은 bill-side 소관 id/name 정본만 보존한다."""
    assert _public_columns("committees") == EXPECTED_COMMITTEE_COLUMNS


def test_bills_has_only_search_oriented_core_columns() -> None:
    """위원회 표시명 중복과 source/link/upstream 컬럼은 bills에 남기지 않는다."""
    assert _public_columns("bills") == EXPECTED_BILL_COLUMNS


def test_votes_has_only_vote_fact_columns() -> None:
    """표결 row는 표결 사실과 시점 정당만 보존한다."""
    assert _public_columns("votes") == EXPECTED_VOTE_COLUMNS


def test_bill_relations_has_only_relationship_columns() -> None:
    """법안 흡수 관계는 관계 자체만 보존한다."""
    assert _public_columns("bill_relations") == EXPECTED_BILL_RELATION_COLUMNS


def test_bill_final_outcomes_has_only_outcome_columns() -> None:
    """최종 처리 이력은 본회의 이후 날짜와 공포 정보만 보존한다."""
    assert _public_columns("bill_final_outcomes") == EXPECTED_BILL_FINAL_OUTCOME_COLUMNS


def test_bill_final_outcomes_bill_no_references_bills_bill_no() -> None:
    assert _fk_columns(
        "bill_final_outcomes",
        "bill_final_outcomes_bill_no_fkey",
    ) == (
        "bill_final_outcomes",
        "bills",
        ["bill_no"],
        ["bill_no"],
    )


def test_bills_committee_id_references_committees_committee_id() -> None:
    assert _fk_columns(
        "bills",
        "bills_committee_id_fkey",
    ) == (
        "bills",
        "committees",
        ["committee_id"],
        ["committee_id"],
    )


def test_high_risk_consumer_columns_have_comments() -> None:
    for table, column in (
        ("committees", "committee_id"),
        ("committees", "committee_name"),
        ("bill_final_outcomes", "bill_no"),
        ("bill_final_outcomes", "govt_transfer_dt"),
        ("bill_final_outcomes", "prom_no"),
        ("bill_source_aliases", "source_bill_id"),
        ("bill_source_aliases", "canonical_bill_id"),
        ("bills", "committee_id"),
        ("votes", "bill_id"),
        ("votes", "mona_cd"),
        ("utterances", "id"),
        ("utterances", "meeting_id"),
        ("utterances", "sequence"),
        ("bill_meeting_contexts", "linked_bill_count"),
        ("bill_meeting_contexts", "utterance_count"),
        ("bill_meeting_contexts", "utterances_by_role"),
        ("bill_meeting_contexts", "evidence_scope"),
    ):
        assert _column_comment(table, column), f"{table}.{column} lacks COMMENT"


def test_meeting_bills_has_only_junction_columns() -> None:
    """회의-법안 junction은 관계 자체만 보존한다."""
    columns = _public_columns("meeting_bills")
    assert columns == {"meeting_id", "bill_id"}
