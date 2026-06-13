"""Slice 4 — bills + bill_coproposers 적재 검증.

실제 국회 API는 호출하지 않고 requests.get만 외부 경계로 대체한다.
DB에는 TEST_BILL_* / TEST_BILL_MEMBER_* 자연키만 사용하고 테스트 전후로 정리한다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.core.db import get_conn
from congress_db.ingest.ingest_bills import backfill_missing_bill_summaries, ingest_bills

TEST_MEMBERS = ("TEST_BILL_MEMBER_1", "TEST_BILL_MEMBER_2", "TEST_BILL_MEMBER_3")
TEST_MEMBER_STUBS = ("TEST_BILL_MEMBER_4",)
TEST_BILLS = ("TEST_BILL_1", "TEST_BILL_2", "TEST_BILL_3")
TEST_COMMITTEES = ("TESTCMT",)


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
            "DELETE FROM committees WHERE committee_id = ANY(%s)",
            (list(TEST_COMMITTEES),),
        )
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
    co_names_text: str,
    lead_names_text: str = "대표",
    cmt_proc_result: str | None = None,
) -> dict[str, str | None]:
    return {
        "BILL_ID": bill_id,
        "BILL_NO": bill_no,
        "BILL_NAME": bill_name,
        "PROPOSE_DT": "2026-05-22",
        "RST_MONA_CD": rst_mona_cd,
        "RST_PROPOSER": lead_names_text,
        "PUBL_MONA_CD": publ_mona_cd,
        "PUBL_PROPOSER": co_names_text,
        "PROPOSER": "대표의원 등 3인",
        "COMMITTEE": "테스트위원회",
        "COMMITTEE_ID": "TESTCMT",
        "PROC_RESULT": None,
        "PROC_DT": None,
        "LAW_PROC_DT": None,
        "COMMITTEE_DT": None,
        "CMT_PROC_DT": None,
        "CMT_PROC_RESULT_CD": cmt_proc_result,
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
            cmt_proc_result="수정가결",
        ),
        _bill_row(
            "TEST_BILL_2",
            "9000002",
            "테스트 법안 2",
            "TEST_BILL_MEMBER_2,TEST_BILL_MEMBER_4",
            "",
            "",
            lead_names_text="대표이,대표사",
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

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

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
    assert first.summary_failures == ()
    assert second.fetched_count == 2
    assert second.upserted_bills == 2
    assert second.upserted_lead_proposers == 3
    assert second.upserted_coproposers == 2

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, bill_no, bill_name, committee_id, cmt_proc_result, proposer, summary
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
        cur.execute(
            """
            SELECT committee_id, committee_name
            FROM committees
            WHERE committee_id = ANY(%s)
            """,
            (list(TEST_COMMITTEES),),
        )
        committees = cur.fetchall()

    assert bills == [
        (
            "TEST_BILL_1",
            "9000001",
            "테스트 법안 1",
            "TESTCMT",
            "수정가결",
            "대표의원 등 3인",
            "요약 9000001",
        ),
        (
            "TEST_BILL_2",
            "9000002",
            "테스트 법안 2",
            "TESTCMT",
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
    assert committees == [("TESTCMT", "테스트위원회")]
    assert (tmp_path / "PARALLEL-BENCHMARK.md").exists()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT hg_nm FROM members WHERE mona_cd = 'TEST_BILL_MEMBER_4'")
        stub = cur.fetchone()

    assert stub == ("대표사",)
    assert any(
        endpoint == "nzmimeepazxkubdpn" and params["pSize"] == "2"
        for endpoint, params in calls
    )


def test_ingest_bills_returns_structured_summary_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = [
        _bill_row(
            "TEST_BILL_1",
            "9000001",
            "테스트 법안 1",
            "TEST_BILL_MEMBER_1",
            "",
            "",
        ),
        _bill_row(
            "TEST_BILL_2",
            "9000002",
            "테스트 법안 2",
            "TEST_BILL_MEMBER_2",
            "",
            "",
        ),
    ]

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if endpoint == "nzmimeepazxkubdpn" and "AGE" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "nzmimeepazxkubdpn":
            response.json.return_value = _envelope(endpoint, total=2, rows=rows)
        elif endpoint == "BPMBILLSUMMARY" and params["BILL_NO"] == "9000002":
            raise RuntimeError("summary API overloaded")
        elif endpoint == "BPMBILLSUMMARY":
            response.json.return_value = _envelope(
                endpoint,
                total=1,
                rows=[{"BILL_NO": params["BILL_NO"], "SUMMARY": "요약"}],
            )
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = ingest_bills(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=0,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert result.summary_success_count == 1
    assert result.summary_error_count == 1
    assert result.summary_failures[0].bill_no == "9000002"
    assert result.summary_failures[0].error == "summary API overloaded"


def test_ingest_bills_incremental_fetches_only_missing_summaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = [
        {
            **_bill_row(
                "TEST_BILL_1",
                "9000001",
                "테스트 법안 1",
                "TEST_BILL_MEMBER_1",
                "",
                "",
            ),
            "PROC_RESULT": "가결",
        },
        _bill_row(
            "TEST_BILL_2",
            "9000002",
            "테스트 법안 2",
            "TEST_BILL_MEMBER_2",
            "",
            "",
        ),
    ]
    summary_calls: list[str] = []
    benchmark_output = tmp_path / "PARALLEL-BENCHMARK.md"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, summary, proc_result)
            VALUES ('TEST_BILL_1', '9000001', '기존 법안명', '기존 요약', '계류')
            """
        )
        conn.commit()

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if endpoint == "nzmimeepazxkubdpn" and "AGE" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "nzmimeepazxkubdpn":
            response.json.return_value = _envelope(endpoint, total=2, rows=rows)
        elif endpoint == "BPMBILLSUMMARY":
            summary_calls.append(params["BILL_NO"])
            if params["BILL_NO"] == "9000001":
                raise AssertionError("existing summary should not be refetched")
            response.json.return_value = _envelope(
                endpoint,
                total=1,
                rows=[{"BILL_NO": params["BILL_NO"], "SUMMARY": "새 요약"}],
            )
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = ingest_bills(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=benchmark_output,
        summary_fetch_mode="missing",
        summary_worker_count=1,
    )

    assert summary_calls == ["9000002"]
    assert result.summary_success_count == 1
    assert result.summary_error_count == 0
    assert result.summary_skipped_count == 1
    assert not benchmark_output.exists()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, summary, proc_result
            FROM bills
            WHERE bill_id = ANY(%s)
            ORDER BY bill_id
            """,
            (list(TEST_BILLS),),
        )
        bills = cur.fetchall()

    assert bills == [
        ("TEST_BILL_1", "기존 요약", "가결"),
        ("TEST_BILL_2", "새 요약", None),
    ]


def test_backfill_missing_bill_summaries_updates_only_missing_summaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    summary_calls: list[str] = []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, propose_dt, summary)
            VALUES
                ('TEST_BILL_1', '9000001', '결측 법안', '2999-01-01', NULL),
                ('TEST_BILL_2', '9000002', '진짜 요약 없음', '2999-01-01', NULL),
                ('TEST_BILL_3', '9000003', '기존 요약 법안', '2999-01-01', '기존 요약')
            """
        )
        conn.commit()

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        assert endpoint == "BPMBILLSUMMARY"
        summary_calls.append(params["BILL_NO"])
        if params["BILL_NO"] == "9000001":
            response.json.return_value = _envelope(
                endpoint,
                total=1,
                rows=[{"BILL_NO": params["BILL_NO"], "SUMMARY": "새 요약"}],
            )
        elif params["BILL_NO"] == "9000002":
            response.json.return_value = _no_data()
        else:
            raise AssertionError("existing summary should not be refetched")
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = backfill_missing_bill_summaries(
        limit=2,
        summary_worker_count=1,
        benchmark_sample_size=1,
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert "9000001" in summary_calls
    assert "9000002" in summary_calls
    assert "9000003" not in summary_calls
    assert result.target_count == 2
    assert result.updated_count == 1
    assert result.no_data_count == 1
    assert result.accepted_gap_count == 1
    assert result.error_count == 0
    assert result.remaining_missing_count >= 1
    assert result.summary_failures == ()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_no, summary
            FROM bills
            WHERE bill_id = ANY(%s)
            ORDER BY bill_id
            """,
            (list(TEST_BILLS),),
        )
        rows = cur.fetchall()

    assert rows == [
        ("9000001", "새 요약"),
        ("9000002", None),
        ("9000003", "기존 요약"),
    ]


def test_backfill_missing_bill_summaries_returns_structured_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, propose_dt, summary)
            VALUES ('TEST_BILL_1', '9000001', '실패 법안', '2999-01-01', NULL)
            """
        )
        conn.commit()

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        raise RuntimeError("summary source overloaded")

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = backfill_missing_bill_summaries(
        limit=1,
        summary_worker_count=1,
        benchmark_sample_size=1,
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert result.target_count == 1
    assert result.updated_count == 0
    assert result.error_count == 1
    assert result.remaining_missing_count >= 1
    assert result.summary_failures[0].bill_no == "9000001"
    assert "summary source overloaded" in result.summary_failures[0].error
