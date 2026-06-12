"""발언 역할 정규화 검증."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from congress_db.core.db import get_conn
from congress_db.ingest.speaker_roles import (
    classify_speaker_role,
    normalize_speaker_roles,
)

TEST_MEETING = 983083
TEST_MEMBER = "TEST_ROLE_MEMBER"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_speaker_role_rows() -> None:
    _delete_test_rows()
    yield
    _delete_test_rows()


def _delete_test_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM utterances WHERE meeting_id = %s", (TEST_MEETING,))
        cur.execute("DELETE FROM meetings WHERE mnts_id = %s", (TEST_MEETING,))
        cur.execute("DELETE FROM members WHERE mona_cd = %s", (TEST_MEMBER,))
        conn.commit()


@pytest.mark.parametrize(
    "speaker_title,speaker_mona_cd,expected",
    [
        ("위원", "TST123", "의원"),
        ("위원", None, "의원"),
        ("의장대리", None, "의원"),
        ("국토교통부장관", None, "국무위원(장관)"),
        ("부총리겸기획재정부장관", None, "국무위원(장관)"),
        ("국무총리", None, "국무위원(장관)"),
        ("보건복지부제1차관", None, "차관"),
        ("증인", None, "증인"),
        ("참고인", None, "참고인"),
        ("전문위원", None, "전문위원"),
        ("수석전문위원", None, "전문위원"),
        ("금융위원장", None, "기타"),
        ("국가인권위원장", None, "기타"),
        ("방송통신위원장후보자", None, "기타"),
        ("법원행정처장", None, "기타"),
        ("법원행정처차장", None, "기타"),
        ("진술인", None, "기타"),
        ("반장", None, "기타"),
        ("국세청장후보자", None, "기타"),
        ("경찰청장직무대행", None, "기타"),
        ("산림청장", None, "기타"),
    ],
)
def test_classify_speaker_role_uses_conservative_title_rules(
    speaker_title: str,
    speaker_mona_cd: str | None,
    expected: str,
) -> None:
    assert classify_speaker_role(speaker_title, speaker_mona_cd) == expected


def test_normalize_speaker_roles_backfills_existing_rows_and_applies_constraints() -> None:
    original_database_url = os.environ["DATABASE_URL"]
    database_name = f"speaker_role_test_{uuid.uuid4().hex}"
    admin_url = _database_url(original_database_url, "postgres")
    test_url = _database_url(original_database_url, database_name)
    _create_database(admin_url, database_name)
    try:
        _apply_schema(test_url)
        os.environ["DATABASE_URL"] = test_url
        _assert_speaker_role_transition()
    finally:
        os.environ["DATABASE_URL"] = original_database_url
        _drop_database(admin_url, database_name)


def _assert_speaker_role_transition() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE utterances ALTER COLUMN speaker_role DROP NOT NULL")
        cur.execute("ALTER TABLE utterances DROP CONSTRAINT IF EXISTS utterances_speaker_role_check")
        cur.execute(
            "INSERT INTO members (mona_cd, hg_nm) VALUES (%s, '역할테스트')",
            (TEST_MEMBER,),
        )
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date)
            VALUES (%s, '발언 역할 테스트 회의', '상임위', '2026-06-10')
            """,
            (TEST_MEETING,),
        )
        cur.execute(
            """
            INSERT INTO utterances (
                meeting_id, sequence, speaker_name, speaker_title,
                speaker_mona_cd, content, speaker_role
            )
            VALUES
                (%s, 1, '역할테스트', '위원', %s, '의원 발언', NULL),
                (%s, 2, '국토부', '국토교통부제1차관', NULL, '정부 발언', NULL),
                (%s, 3, '장관', '국토교통부장관', NULL, '장관 발언', NULL),
                (%s, 4, '증인', '증인', NULL, '증인 발언', NULL),
                (%s, 5, '금융위', '금융위원장', NULL, '기타 발언', NULL)
            """,
            (
                TEST_MEETING,
                TEST_MEMBER,
                TEST_MEETING,
                TEST_MEETING,
                TEST_MEETING,
                TEST_MEETING,
            ),
        )
        conn.commit()

    result = normalize_speaker_roles(other_threshold=1)

    assert result.null_speaker_role_count == 0
    assert result.role_distribution["의원"] >= 1
    assert result.role_distribution["차관"] >= 1
    assert result.role_distribution["국무위원(장관)"] >= 1
    assert result.role_distribution["증인"] >= 1
    assert any(row.speaker_title == "금융위원장" for row in result.high_frequency_other_titles)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT sequence, speaker_role
            FROM utterances
            WHERE meeting_id = %s
            ORDER BY sequence
            """,
            (TEST_MEETING,),
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT sequence
            FROM utterances
            WHERE meeting_id = %s
              AND speaker_role IN ('국무위원(장관)', '차관')
            ORDER BY sequence
            """,
            (TEST_MEETING,),
        )
        government_sequences = [row[0] for row in cur.fetchall()]
        cur.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'utterances'
              AND column_name = 'speaker_role'
            """
        )
        is_nullable = cur.fetchone()[0]
        cur.execute(
            """
            SELECT convalidated
            FROM pg_constraint
            WHERE conrelid = 'utterances'::regclass
              AND conname = 'utterances_speaker_role_check'
            """
        )
        check_row = cur.fetchone()

    assert rows == [
        (1, "의원"),
        (2, "차관"),
        (3, "국무위원(장관)"),
        (4, "증인"),
        (5, "기타"),
    ]
    assert government_sequences == [2, 3]
    assert is_nullable == "NO"
    assert check_row == (True,)

    with get_conn() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO utterances (
                    meeting_id, sequence, speaker_name, speaker_title, content, speaker_role
                )
                VALUES (%s, 99, '오류', '오류', '오류', '엉뚱역할')
                """,
                (TEST_MEETING,),
            )
        conn.rollback()


def _database_url(base_url: str, database_name: str) -> str:
    params = conninfo_to_dict(base_url)
    params["dbname"] = database_name
    return make_conninfo(**params)


def _create_database(admin_url: str, database_name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))


def _drop_database(admin_url: str, database_name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )


def _apply_schema(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute((REPO_ROOT / "db/schema.sql").read_text())
        cur.execute((REPO_ROOT / "db/migrations/008_speaker_role.sql").read_text())
        conn.commit()
