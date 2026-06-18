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
        "proposer_raw",
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

DIRECT_SQL_BASE_TABLES = frozenset(
    {
        "members",
        "committees",
        "bills",
        "bill_lead_proposers",
        "bill_coproposers",
        "votes",
        "meetings",
        "utterances",
        "meeting_bills",
        "bill_final_outcomes",
        "bill_relations",
        "bill_source_aliases",
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


def _relation_comment(relation: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT obj_description(%s::regclass)", (f"public.{relation}",))
            row = cur.fetchone()
            return row[0] if row else None


def _function_comment(name: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT obj_description(oid) FROM pg_proc WHERE proname = %s",
                (name,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _unindexed_fk_columns() -> list[tuple[str, str]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.conrelid::regclass::text AS table_name,
                       a.attname AS fk_column
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid
                 AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'f'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pg_index i
                      WHERE i.indrelid = c.conrelid
                        AND a.attnum = ANY(i.indkey)
                  )
                ORDER BY table_name, fk_column
                """
            )
            return [(row[0], row[1]) for row in cur.fetchall()]


def _rls_enabled_tables() -> set[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND c.relrowsecurity
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
        ("bill_final_outcomes", "prom_law_nm"),
        ("bill_source_aliases", "source_bill_id"),
        ("bill_source_aliases", "canonical_bill_id"),
        ("bills", "proposer_raw"),
        ("bills", "committee_id"),
        ("bills", "committee_dt"),
        ("bills", "cmt_proc_dt"),
        ("bills", "law_proc_dt"),
        ("votes", "bill_id"),
        ("votes", "mona_cd"),
        ("utterances", "id"),
        ("utterances", "meeting_id"),
        ("utterances", "sequence"),
        ("bill_meeting_contexts", "linked_bill_count"),
        ("bill_meeting_contexts", "utterance_count"),
        ("bill_meeting_contexts", "utterances_by_role"),
        ("bill_meeting_contexts", "evidence_scope"),
        # raw 원천명 노출 컬럼 — GROUP BY 시 조용한 NULL 버킷/값목록을 introspect로 알려야 함
        ("members", "sex_gbn_nm"),
        ("meetings", "meeting_type"),
    ):
        assert _column_comment(table, column), f"{table}.{column} lacks COMMENT"


def test_critical_gotcha_comments_carry_their_warning() -> None:
    """함정 COMMENT는 경고 문구 자체를 보존해야 한다.

    COMMENT는 last-write-wins이라 후속 migration이 경고 없는 문구로 덮으면(과거 026이 013을
    덮은 사례) 소비자가 introspect해도 함정을 못 본다. 핵심 함정은 키워드 존재로 잠근다.
    """
    column_markers = {
        # 공포 이름 bridge: prom_no를 권장 키로 가리켜야 함
        ("bill_final_outcomes", "prom_law_nm"): "prom_no",
        # 대안/정부 법안의 체계적 NULL 경고
        ("bills", "committee_dt"): "대안",
        ("bills", "law_proc_dt"): "공포일이 아님",
        # 거부권 후 재의결 추론(가결-미공포 구분)
        ("bill_final_outcomes", "promulgation_dt"): "거부권",
        # 성별 GROUP BY 시 NULL 버킷 stub 경고
        ("members", "sex_gbn_nm"): "NULL",
    }
    for (table, column), marker in column_markers.items():
        comment = _column_comment(table, column) or ""
        assert marker in comment, f"{table}.{column} COMMENT lost its warning ('{marker}')"

    relation_markers = {
        # 발의자 정당 NULL 함정
        "bill_coproposers": "poly_nm",
        # bill_lineage 커버리지(소관위-종료 원안 부재)
        "bill_lineage": "COVERAGE",
        # bills 테이블에 생애주기 단계 시간순 개요(introspect-only 자립)
        "bills": "생애주기 단계",
        # bill_meeting_contexts fanout 단위(회의당) 명시
        "bill_meeting_contexts": "회의당",
    }
    for relation, marker in relation_markers.items():
        comment = _relation_comment(relation) or ""
        assert marker in comment, f"{relation} COMMENT lost its warning ('{marker}')"

    # 검색 함수 성능 절벽(2글자 trigram 미사용) 경고 — recall만 남고 성능이 덮이는 회귀 방지
    for func in ("search_bills", "search_utterances"):
        comment = _function_comment(func) or ""
        assert "3-gram" in comment, f"{func} COMMENT lost its 2-char performance warning"


def test_foreign_key_columns_are_indexed_for_direct_sql_joins() -> None:
    """FK columns stay indexed because direct-SQL consumers join through the DB itself."""
    assert _unindexed_fk_columns() == []


def test_direct_sql_base_tables_do_not_hide_rows_behind_rls() -> None:
    """congress_ro is controlled by GRANT allowlist; RLS without policies returns 0 rows."""
    assert not (DIRECT_SQL_BASE_TABLES & _rls_enabled_tables())


def test_meeting_bills_has_only_junction_columns() -> None:
    """회의-법안 junction은 관계 자체만 보존한다."""
    columns = _public_columns("meeting_bills")
    assert columns == {"meeting_id", "bill_id"}
