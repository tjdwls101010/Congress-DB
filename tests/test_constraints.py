"""Slice 1 RGR 3 — 핵심 제약(PK/FK/UNIQUE/CHECK)이 ERD대로 들어갔는지 검증.

모든 INSERT 후에는 rollback해서 DB 상태에 영향을 남기지 않는다.
다른 테스트(test_schema)와의 격리를 유지하기 위해서다.
"""

from __future__ import annotations

import psycopg
import pytest

from congress_db.core.db import get_conn


# -------------------------------------------------------------------------
# PK 검증
# -------------------------------------------------------------------------

def _pk_columns(table: str) -> list[str]:
    """주어진 테이블의 PK 컬럼명을 정의 순서대로 반환."""
    sql = """
        SELECT a.attname
        FROM pg_constraint c
        JOIN pg_class t      ON t.oid = c.conrelid
        JOIN pg_namespace n  ON n.oid = t.relnamespace
        JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a  ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE n.nspname = 'public'
          AND t.relname = %s
          AND c.contype = 'p'
        ORDER BY k.ord
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (table,))
        return [r[0] for r in cur.fetchall()]


@pytest.mark.parametrize(
    "table,expected_pk",
    [
        ("members",          ["mona_cd"]),
        ("bills",            ["bill_id"]),
        ("meetings",         ["mnts_id"]),
        ("bill_relations",   ["absorbed_bill_id"]),
        ("bill_lead_proposers", ["bill_id", "mona_cd"]),
        ("bill_coproposers", ["bill_id", "mona_cd"]),
        ("votes",            ["id"]),
        ("meeting_bills",    ["meeting_id", "bill_id"]),
        ("utterances",       ["id"]),
        ("api_catalog",      ["inf_id"]),
        ("ingest_runs",      ["id"]),
        ("ingest_cursors",   ["source"]),
        ("dead_letters",     ["id"]),
    ],
)
def test_primary_keys(table: str, expected_pk: list[str]) -> None:
    assert _pk_columns(table) == expected_pk


# -------------------------------------------------------------------------
# CHECK 제약: meetings.meeting_type
# -------------------------------------------------------------------------

def test_meeting_type_rejects_invalid_value() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO meetings
                    (mnts_id, title, meeting_type, conf_date)
                VALUES (999991, 'test', '엉뚱회의', '2024-06-01')
                """
            )
        conn.rollback()


@pytest.mark.parametrize(
    "valid_type",
    ["본회의", "상임위", "특별위", "국정감사", "국정조사", "인사청문회", "소위원회"],
)
def test_meeting_type_accepts_each_valid_value(valid_type: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings
                (mnts_id, title, meeting_type, conf_date)
            VALUES (999992, 'test', %s, '2024-06-01')
            """,
            (valid_type,),
        )
        conn.rollback()


# -------------------------------------------------------------------------
# FK 제약: bills.rst_mona_cd → members.mona_cd (단일 대표발의 편의 FK)
# -------------------------------------------------------------------------

def test_bills_fk_rejects_nonexistent_member() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                """
                INSERT INTO bills (bill_id, bill_no, bill_name, rst_mona_cd)
                VALUES ('TESTFK', 'B9999991', 'FK 테스트', 'NONEXISTENT')
                """
            )
        conn.rollback()


# -------------------------------------------------------------------------
# UNIQUE 제약: votes(bill_id, mona_cd), utterances(meeting_id, sequence),
#              bills.bill_no
# -------------------------------------------------------------------------

def test_votes_unique_bill_mona() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO members (mona_cd, hg_nm) VALUES ('TESTM1', '테스트의원1')"
        )
        cur.execute(
            "INSERT INTO bills (bill_id, bill_no, bill_name) "
            "VALUES ('TESTB1', 'B9999992', '테스트법안1')"
        )
        cur.execute(
            "INSERT INTO votes (bill_id, mona_cd, vote_date, result_vote_mod) "
            "VALUES ('TESTB1', 'TESTM1', '2024-06-01', '찬성')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO votes (bill_id, mona_cd, vote_date, result_vote_mod) "
                "VALUES ('TESTB1', 'TESTM1', '2024-06-02', '반대')"
            )
        conn.rollback()


def test_utterances_unique_meeting_sequence() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings
                (mnts_id, title, meeting_type, conf_date)
            VALUES (999993, 'test', '본회의', '2024-06-01')
            """
        )
        cur.execute(
            "INSERT INTO utterances "
            "(meeting_id, sequence, speaker_name, speaker_title, content) "
            "VALUES (999993, 1, '의장', '의장', '개회합니다')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO utterances "
                "(meeting_id, sequence, speaker_name, speaker_title, content) "
                "VALUES (999993, 1, '다른', '의원', '중복 시퀀스')"
            )
        conn.rollback()


def test_bills_bill_no_unique() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bills (bill_id, bill_no, bill_name) "
            "VALUES ('U1', 'BNO_UNQ1', '유니크 테스트')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO bills (bill_id, bill_no, bill_name) "
                "VALUES ('U2', 'BNO_UNQ1', '같은 번호 다른 id')"
            )
        conn.rollback()


def test_bill_relations_require_known_absorbed_bill_and_valid_relation_type() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bills (bill_id, bill_no, bill_name) "
            "VALUES ('REL_ABSORB', 'RELNO1', '흡수 원안')"
        )
        cur.execute(
            "INSERT INTO bills (bill_id, bill_no, bill_name) "
            "VALUES ('REL_ALT', 'RELNO2', '흡수 대안')"
        )
        cur.execute(
            """
            INSERT INTO bill_relations (
                absorbed_bill_id, alternative_bill_id, relation_type
            )
            VALUES ('REL_ABSORB', 'REL_ALT', '대안반영')
            """
        )
        cur.execute(
            """
            INSERT INTO bill_relations (
                absorbed_bill_id, alternative_bill_id, relation_type
            )
            VALUES ('REL_ALT', 'MISSING_ALT_SOURCE_KEY', '수정안반영')
            """
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO bill_relations (
                    absorbed_bill_id, alternative_bill_id, relation_type
                )
                VALUES ('REL_ALT', 'REL_ABSORB', '엉뚱관계')
                """
            )
        conn.rollback()
