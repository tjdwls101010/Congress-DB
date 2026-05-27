"""Slice 4 — bills + bill_coproposers 적재 검증.

실제 국회 API는 호출하지 않고 requests.get만 외부 경계로 대체한다.
DB에는 TEST_BILL_* / TEST_BILL_MEMBER_* 자연키만 사용하고 테스트 전후로 정리한다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.db import get_conn
from congress_db.ingest_bills import ingest_bills

TEST_MEMBERS = ("TEST_BILL_MEMBER_1", "TEST_BILL_MEMBER_2", "TEST_BILL_MEMBER_3")
TEST_MEMBER_STUBS = ("TEST_BILL_MEMBER_4",)
TEST_BILLS = ("TEST_BILL_1", "TEST_BILL_2")


@pytest.fixture(autouse=True)
def clean_bill_rows() -> None:
    _delete_bill_rows()
    _insert_test_members()
    yield
    _delete_bill_rows()


def _delete_bill_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM bill_coproposers WHERE bill_id = ANY(%s)",
            (list(TEST_BILLS),),
        )
        cur.execute(
            "DELETE FROM bill_lead_proposers WHERE bill_id = ANY(%s)",
            (list(TEST_BILLS),),
        )
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_BILLS),))
        cur.execute(
            "DELETE FROM members WHERE mona_cd = ANY(%s)",
            (list(TEST_MEMBERS + TEST_MEMBER_STUBS),),
        )
        conn.commit()


def _insert_test_members() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        for code in TEST_MEMBERS:
            cur.execute(
                """
                INSERT INTO members (mona_cd, hg_nm)
                VALUES (%s, %s)
                ON CONFLICT (mona_cd) DO NOTHING
                """,
                (code, code),
            )
        conn.commit()


def _bill_row(
    bill_id: str,
    bill_no: str,
    bill_name: str,
    rst_mona_cd: str,
    publ_mona_cd: str,
    publ_proposer: str,
    rst_proposer: str = "대표",
) -> dict[str, str | None]:
    return {
        "BILL_ID": bill_id,
        "BILL_NO": bill_no,
        "BILL_NAME": bill_name,
        "PROPOSE_DT": "2026-05-22",
        "RST_MONA_CD": rst_mona_cd,
        "RST_PROPOSER": rst_proposer,
        "PUBL_MONA_CD": publ_mona_cd,
        "PUBL_PROPOSER": publ_proposer,
        "PROPOSER": "대표의원 등 3인",
        "COMMITTEE": "테스트위원회",
        "COMMITTEE_ID": "TESTCMT",
        "PROC_RESULT": None,
        "PROC_DT": None,
        "LAW_PROC_DT": None,
        "LAW_PROC_RESULT_CD": None,
        "COMMITTEE_DT": None,
        "CMT_PROC_DT": None,
        "CMT_PROC_RESULT_CD": None,
        "DETAIL_LINK": "https://example.com/bill",
        "AGE": "22",
    }


def _envelope(endpoint: str, total: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        endpoint: [
            {"head": [{"list_total_count": total}, {"RESULT": {"CODE": "INFO-000"}}]},
            {"row": rows},
        ]
    }


def _no_data() -> dict[str, Any]:
    return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}


def test_ingest_bills_upserts_bills_and_coproposers_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = [
        _bill_row(
            "TEST_BILL_1",
            "9000001",
            "테스트 법안 1",
            "TEST_BILL_MEMBER_1",
            "TEST_BILL_MEMBER_2,TEST_BILL_MEMBER_3",
            "공동이,공동삼",
        ),
        _bill_row(
            "TEST_BILL_2",
            "9000002",
            "테스트 법안 2",
            "TEST_BILL_MEMBER_2,TEST_BILL_MEMBER_4",
            "",
            "",
            rst_proposer="대표이,대표사",
        ),
    ]
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        calls.append((endpoint, dict(params)))
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if endpoint == "nzmimeepazxkubdpn" and "AGE" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "nzmimeepazxkubdpn":
            response.json.return_value = _envelope(endpoint, total=2, rows=rows)
        elif endpoint == "BPMBILLSUMMARY":
            summary = f"요약 {params['BILL_NO']}"
            response.json.return_value = _envelope(
                endpoint,
                total=1,
                rows=[{"BILL_NO": params["BILL_NO"], "SUMMARY": summary}],
            )
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.api_client.requests.get", fake_get)

    first = ingest_bills(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )
    second = ingest_bills(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert first.fetched_count == 2
    assert first.upserted_bills == 2
    assert first.upserted_lead_proposers == 3
    assert first.upserted_coproposers == 2
    assert second.fetched_count == 2
    assert second.upserted_bills == 2
    assert second.upserted_lead_proposers == 3
    assert second.upserted_coproposers == 2

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, bill_no, bill_name, rst_mona_cd, publ_proposer,
                   proposer, summary
            FROM bills
            WHERE bill_id = ANY(%s)
            ORDER BY bill_id
            """,
            (list(TEST_BILLS),),
        )
        bills = cur.fetchall()
        cur.execute(
            """
            SELECT bill_id, mona_cd, order_no
            FROM bill_lead_proposers
            WHERE bill_id = ANY(%s)
            ORDER BY bill_id, order_no
            """,
            (list(TEST_BILLS),),
        )
        lead_proposers = cur.fetchall()
        cur.execute(
            """
            SELECT bill_id, mona_cd, order_no
            FROM bill_coproposers
            WHERE bill_id = ANY(%s)
            ORDER BY bill_id, order_no
            """,
            (list(TEST_BILLS),),
        )
        coproposers = cur.fetchall()

    assert bills == [
        (
            "TEST_BILL_1",
            "9000001",
            "테스트 법안 1",
            "TEST_BILL_MEMBER_1",
            "공동이,공동삼",
            "대표의원 등 3인",
            "요약 9000001",
        ),
        (
            "TEST_BILL_2",
            "9000002",
            "테스트 법안 2",
            None,
            None,
            "대표의원 등 3인",
            "요약 9000002",
        ),
    ]
    assert lead_proposers == [
        ("TEST_BILL_1", "TEST_BILL_MEMBER_1", 1),
        ("TEST_BILL_2", "TEST_BILL_MEMBER_2", 1),
        ("TEST_BILL_2", "TEST_BILL_MEMBER_4", 2),
    ]
    assert coproposers == [
        ("TEST_BILL_1", "TEST_BILL_MEMBER_2", 1),
        ("TEST_BILL_1", "TEST_BILL_MEMBER_3", 2),
    ]
    assert (tmp_path / "PARALLEL-BENCHMARK.md").exists()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT hg_nm FROM members WHERE mona_cd = 'TEST_BILL_MEMBER_4'")
        stub = cur.fetchone()

    assert stub == ("대표사",)
    assert any(
        endpoint == "nzmimeepazxkubdpn" and params["pSize"] == "2"
        for endpoint, params in calls
    )
