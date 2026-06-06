"""Slice 3 — members 적재 검증.

실제 국회 API는 호출하지 않고 requests.get만 외부 경계로 대체한다.
DB에는 TEST_MEMBER_* 자연키만 사용하고 테스트 전후로 해당 행만 정리한다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.core.db import get_conn
from congress_db.ingest.ingest_members import ingest_members

TEST_MEMBER_CODES = (
    "TEST_MEMBER_1",
    "TEST_MEMBER_2",
    "TEST_MEMBER_DEPARTED",
    "TEST_MEMBER_STUB",
)


@pytest.fixture(autouse=True)
def clean_test_members() -> None:
    _delete_test_members()
    yield
    _delete_test_members()


def _delete_test_members() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM members WHERE mona_cd = ANY(%s)",
            (list(TEST_MEMBER_CODES),),
        )
        conn.commit()


def _member_row(
    mona_cd: str,
    hg_nm: str,
    hj_nm: str,
    *,
    poly_nm: str = "테스트정당",
    mem_title: str = "긴 약력\n두 번째 줄",
) -> dict[str, str]:
    return {
        "MONA_CD": mona_cd,
        "HG_NM": hg_nm,
        "HJ_NM": hj_nm,
        "ENG_NM": "TEST MEMBER",
        "BTH_DATE": "1970-01-01",
        "SEX_GBN_NM": "남",
        "POLY_NM": poly_nm,
        "ORIG_NM": "테스트선거구",
        "ELECT_GBN_NM": "지역구",
        "CMITS": "테스트위원회",
        "REELE_GBN_NM": "초선",
        "UNITS": "제22대",
        "TEL_NO": "02-0000-0000",
        "E_MAIL": "member@example.com",
        "HOMEPAGE": "https://example.com",
        "MEM_TITLE": mem_title,
        "ASSEM_ADDR": "의원회관 000호",
    }


def _members_payload(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "nwvrqwxyaytdsfvhu": [
            {"head": [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]},
            {"row": rows},
        ]
    }


def test_ingest_members_fetches_once_and_upserts_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _member_row("TEST_MEMBER_1", "테스트일", "姜景淑"),
        _member_row("TEST_MEMBER_2", "테스트이", "金二", mem_title="약력 원문\r\n보존"),
    ]
    calls: list[dict[str, Any]] = []

    def fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        calls.append(kwargs)
        response = MagicMock()
        response.json.return_value = _members_payload(rows)
        response.raise_for_status = MagicMock()
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    first = ingest_members()
    second = ingest_members()

    assert first.fetched_count == 2
    assert second.fetched_count == 2
    assert len(calls) == 2
    assert all(call["params"]["pSize"] == "300" for call in calls)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mona_cd, hg_nm, hj_nm, mem_title
            FROM members
            WHERE mona_cd = ANY(%s)
            ORDER BY mona_cd
            """,
            (list(TEST_MEMBER_CODES),),
        )
        saved = cur.fetchall()

    assert saved == [
        ("TEST_MEMBER_1", "테스트일", "姜景淑", "긴 약력\n두 번째 줄"),
        ("TEST_MEMBER_2", "테스트이", "金二", "약력 원문\r\n보존"),
    ]


def test_ingest_members_updates_existing_member_and_fetched_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO members (mona_cd, hg_nm, hj_nm, poly_nm, fetched_at)
            VALUES ('TEST_MEMBER_1', '옛이름', '舊', '옛정당', '2000-01-01')
            """
        )
        conn.commit()

    rows = [_member_row("TEST_MEMBER_1", "새이름", "新", poly_nm="새정당")]

    def fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        response = MagicMock()
        response.json.return_value = _members_payload(rows)
        response.raise_for_status = MagicMock()
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    ingest_members()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT hg_nm, hj_nm, poly_nm, fetched_at > '2000-01-01'::timestamptz
            FROM members
            WHERE mona_cd = 'TEST_MEMBER_1'
            """
        )
        saved = cur.fetchone()

    assert saved == ("새이름", "新", "새정당", True)


def test_ingest_members_marks_only_latest_roster_as_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO members (mona_cd, hg_nm, is_incumbent)
            VALUES
                ('TEST_MEMBER_1', '직전현직', TRUE),
                ('TEST_MEMBER_DEPARTED', '명부이탈', TRUE),
                ('TEST_MEMBER_STUB', '표결전용stub', FALSE)
            """
        )
        conn.commit()

    rows = [
        _member_row("TEST_MEMBER_1", "계속현직", "現"),
        _member_row("TEST_MEMBER_2", "신규현직", "新"),
    ]

    def fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        response = MagicMock()
        response.json.return_value = _members_payload(rows)
        response.raise_for_status = MagicMock()
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    ingest_members()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mona_cd, hg_nm, is_incumbent
            FROM members
            WHERE mona_cd = ANY(%s)
            ORDER BY mona_cd
            """,
            (list(TEST_MEMBER_CODES),),
        )
        saved = cur.fetchall()

    assert saved == [
        ("TEST_MEMBER_1", "계속현직", True),
        ("TEST_MEMBER_2", "신규현직", True),
        ("TEST_MEMBER_DEPARTED", "명부이탈", False),
        ("TEST_MEMBER_STUB", "표결전용stub", False),
    ]
