"""Slice 5 — votes 적재 검증."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.core.db import get_conn
from congress_db.ingest.ingest_votes import _validate_vote_distribution, ingest_votes

TEST_BILLS = (
    "TEST_VOTE_BILL_1",
    "TEST_VOTE_BILL_2",
    "TEST_VOTE_BILL_EXISTING",
    "TEST_VOTE_BILL_ALIAS",
)
TEST_MEMBERS = ("TEST_VOTE_MEMBER_1", "TEST_VOTE_MEMBER_2", "TEST_VOTE_MEMBER_3")
TEST_COMMITTEES = ("TESTCMT",)


@pytest.fixture(autouse=True)
def clean_vote_rows() -> None:
    _delete_vote_rows()
    yield
    _delete_vote_rows()


def _delete_vote_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM votes WHERE bill_id = ANY(%s)", (list(TEST_BILLS),))
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_BILLS),))
        cur.execute(
            "DELETE FROM committees WHERE committee_id = ANY(%s)",
            (list(TEST_COMMITTEES),),
        )
        cur.execute("DELETE FROM members WHERE mona_cd = ANY(%s)", (list(TEST_MEMBERS),))
        conn.commit()


def _envelope(endpoint: str, total: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        endpoint: [
            {"head": [{"list_total_count": total}, {"RESULT": {"CODE": "INFO-000"}}]},
            {"row": rows},
        ]
    }


def _no_data() -> dict[str, Any]:
    return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}


def _error(message: str = "필수 값이 누락되어 있습니다. 요청인자를 참고 하십시오.") -> dict[str, Any]:
    return {"RESULT": {"CODE": "ERROR-300", "MESSAGE": message}}


def _vote_bill_row(bill_id: str, bill_no: str, bill_name: str) -> dict[str, Any]:
    return {
        "BILL_ID": bill_id,
        "BILL_NO": bill_no,
        "BILL_NAME": bill_name,
        "PROC_DT": "2026-05-07",
        "PROC_RESULT_CD": "원안가결",
        "CURR_COMMITTEE": "테스트위원회",
        "CURR_COMMITTEE_ID": "TESTCMT",
        "LINK_URL": "https://example.com/vote-bill",
        "AGE": "22",
        "MEMBER_TCNT": 3,
        "VOTE_TCNT": 3,
        "YES_TCNT": 1,
        "NO_TCNT": 1,
        "BLANK_TCNT": 1,
    }


def _vote_row(
    bill_id: str,
    bill_no: str,
    mona_cd: str,
    hg_nm: str,
    result: str,
) -> dict[str, Any]:
    return {
        "BILL_ID": bill_id,
        "BILL_NO": bill_no,
        "BILL_NAME": "테스트 표결 법안",
        "MONA_CD": mona_cd,
        "HG_NM": hg_nm,
        "VOTE_DATE": "20260507 181630",
        "RESULT_VOTE_MOD": result,
        "POLY_NM": "테스트정당",
    }


def test_ingest_votes_upserts_vote_rows_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    vote_bills = [
        _vote_bill_row("TEST_VOTE_BILL_1", "9100001", "테스트 표결 법안 1"),
        _vote_bill_row("TEST_VOTE_BILL_2", "9100002", "테스트 표결 법안 2"),
    ]
    vote_rows_by_bill = {
        "TEST_VOTE_BILL_1": [
            _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_1", "표결일", "찬성"),
            _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_2", "표결이", "반대"),
            _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_3", "표결삼", "기권"),
        ],
        "TEST_VOTE_BILL_2": [
            _vote_row("TEST_VOTE_BILL_2", "9100002", "TEST_VOTE_MEMBER_1", "표결일", "찬성"),
            _vote_row("TEST_VOTE_BILL_2", "9100002", "TEST_VOTE_MEMBER_2", "표결이", "반대"),
            _vote_row("TEST_VOTE_BILL_2", "9100002", "TEST_VOTE_MEMBER_3", "표결삼", "기권"),
        ],
    }

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "AGE" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _envelope(endpoint, total=2, rows=vote_bills)
        elif endpoint == "nojepdqqaweusdfbi":
            rows = vote_rows_by_bill[params["BILL_ID"]]
            response.json.return_value = _envelope(endpoint, total=len(rows), rows=rows)
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    first = ingest_votes(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "VOTES-PARALLEL-BENCHMARK.md",
    )
    second = ingest_votes(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "VOTES-PARALLEL-BENCHMARK.md",
    )

    assert first.target_bill_count == 2
    assert first.vote_row_count == 6
    assert first.upserted_votes == 6
    assert first.selected_worker_count == 1
    assert first.failed_vote_bill_count == 0
    assert second.vote_row_count == 6
    assert second.upserted_votes == 6

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM votes WHERE bill_id = ANY(%s)", (list(TEST_BILLS),))
        vote_count = cur.fetchone()
        cur.execute(
            """
            SELECT bill_id, mona_cd, result_vote_mod, poly_nm_at_vote
            FROM votes
            WHERE bill_id = 'TEST_VOTE_BILL_1'
            ORDER BY mona_cd
            """
        )
        votes = cur.fetchall()
        cur.execute("SELECT hg_nm FROM members WHERE mona_cd = 'TEST_VOTE_MEMBER_3'")
        member_stub = cur.fetchone()
        cur.execute(
            """
            SELECT bill_name, committee_id, proc_result
            FROM bills
            WHERE bill_id = 'TEST_VOTE_BILL_1'
            """
        )
        bill_stub = cur.fetchone()
        cur.execute(
            """
            SELECT committee_id, committee_name
            FROM committees
            WHERE committee_id = 'TESTCMT'
            """
        )
        committee = cur.fetchone()

    assert vote_count == (6,)
    assert votes == [
        ("TEST_VOTE_BILL_1", "TEST_VOTE_MEMBER_1", "찬성", "테스트정당"),
        ("TEST_VOTE_BILL_1", "TEST_VOTE_MEMBER_2", "반대", "테스트정당"),
        ("TEST_VOTE_BILL_1", "TEST_VOTE_MEMBER_3", "기권", "테스트정당"),
    ]
    assert member_stub == ("표결삼",)
    assert bill_stub == ("테스트 표결 법안 1", "TESTCMT", "원안가결")
    assert committee == ("TESTCMT", "테스트위원회")


def test_ingest_votes_retries_transient_vote_row_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    vote_bills = [_vote_bill_row("TEST_VOTE_BILL_1", "9100001", "테스트 표결 법안 1")]
    vote_rows = [
        _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_1", "표결일", "찬성"),
        _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_2", "표결이", "반대"),
        _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_3", "표결삼", "기권"),
    ]
    row_endpoint_calls = 0

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        nonlocal row_endpoint_calls
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "AGE" not in params and endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _no_data()
        elif endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _envelope(endpoint, total=1, rows=vote_bills)
        elif endpoint == "nojepdqqaweusdfbi":
            row_endpoint_calls += 1
            if row_endpoint_calls <= 4:
                response.json.return_value = _error()
            elif "AGE" in params:
                response.json.return_value = _envelope(endpoint, total=3, rows=vote_rows)
            else:
                response.json.return_value = _error()
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = ingest_votes(
        limit_pct=1.0,
        page_size=1,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "VOTES-PARALLEL-BENCHMARK.md",
        retry_delays=(0.0,),
    )

    assert result.vote_row_count == 3
    assert result.failed_vote_bill_count == 0
    assert row_endpoint_calls > 4


def test_ingest_votes_returns_structured_failures_when_partial_allowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    vote_bills = [_vote_bill_row("TEST_VOTE_BILL_1", "9100001", "테스트 표결 법안 1")]

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "AGE" not in params and endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _no_data()
        elif endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _envelope(endpoint, total=1, rows=vote_bills)
        elif endpoint == "nojepdqqaweusdfbi":
            response.json.return_value = _error("source item unavailable")
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = ingest_votes(
        limit_pct=1.0,
        page_size=1,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "VOTES-PARALLEL-BENCHMARK.md",
        retry_delays=(),
        allow_partial=True,
    )

    assert result.vote_row_count == 0
    assert result.failed_vote_bill_count == 1
    assert result.vote_row_failures[0].bill_id == "TEST_VOTE_BILL_1"
    assert "source item unavailable" in result.vote_row_failures[0].error


def test_vote_distribution_allows_gap_when_member_vote_api_omits_member() -> None:
    vote_bill = {
        "BILL_ID": "TEST_VOTE_BILL_GAP",
        "MEMBER_TCNT": 4,
        "VOTE_TCNT": 3,
        "YES_TCNT": 2,
        "NO_TCNT": 1,
        "BLANK_TCNT": 0,
    }
    vote_rows = [
        {"RESULT_VOTE_MOD": "찬성"},
        {"RESULT_VOTE_MOD": "반대"},
        {"RESULT_VOTE_MOD": "불참"},
    ]

    assert _validate_vote_distribution(vote_bill, vote_rows) is False


def test_vote_distribution_allows_small_category_mismatch_when_vote_total_matches() -> None:
    vote_bill = {
        "BILL_ID": "TEST_VOTE_BILL_CATEGORY_MISMATCH",
        "MEMBER_TCNT": 296,
        "VOTE_TCNT": 197,
        "YES_TCNT": 195,
        "NO_TCNT": 0,
        "BLANK_TCNT": 2,
    }
    vote_rows = (
        [{"RESULT_VOTE_MOD": "찬성"}] * 196
        + [{"RESULT_VOTE_MOD": "기권"}]
        + [{"RESULT_VOTE_MOD": "불참"}] * 98
    )

    assert _validate_vote_distribution(vote_bill, vote_rows) is False


def test_ingest_votes_uses_existing_bill_when_vote_api_reuses_bill_no(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    vote_bills = [
        _vote_bill_row(
            "TEST_VOTE_BILL_ALIAS",
            "9100003",
            "표결 API의 다른 BILL_ID",
        )
    ]
    vote_rows_by_bill = {
        "TEST_VOTE_BILL_ALIAS": [
            _vote_row(
                "TEST_VOTE_BILL_ALIAS",
                "9100003",
                "TEST_VOTE_MEMBER_1",
                "표결일",
                "찬성",
            ),
            _vote_row(
                "TEST_VOTE_BILL_ALIAS",
                "9100003",
                "TEST_VOTE_MEMBER_2",
                "표결이",
                "반대",
            ),
            _vote_row(
                "TEST_VOTE_BILL_ALIAS",
                "9100003",
                "TEST_VOTE_MEMBER_3",
                "표결삼",
                "기권",
            ),
        ]
    }
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name)
            VALUES ('TEST_VOTE_BILL_EXISTING', '9100003', '기존 법안')
            """
        )
        conn.commit()

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "AGE" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _envelope(endpoint, total=1, rows=vote_bills)
        elif endpoint == "nojepdqqaweusdfbi":
            response.json.return_value = _envelope(
                endpoint,
                total=3,
                rows=vote_rows_by_bill[params["BILL_ID"]],
            )
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = ingest_votes(
        limit_pct=1.0,
        page_size=1,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "VOTES-PARALLEL-BENCHMARK.md",
    )

    assert result.upserted_votes == 3
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bills WHERE bill_id = 'TEST_VOTE_BILL_ALIAS'")
        alias_bill_count = cur.fetchone()
        cur.execute(
            """
            SELECT DISTINCT bill_id
            FROM votes
            WHERE mona_cd = ANY(%s)
            """,
            (list(TEST_MEMBERS),),
        )
        vote_bill_ids = cur.fetchall()

    assert alias_bill_count == (0,)
    assert vote_bill_ids == [("TEST_VOTE_BILL_EXISTING",)]


def test_ingest_votes_incremental_fetches_only_missing_vote_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    existing_vote_bill = {
        **_vote_bill_row("TEST_VOTE_BILL_1", "9100001", "테스트 표결 법안 1"),
        "PROC_RESULT_CD": "수정가결",
    }
    new_vote_bill = _vote_bill_row("TEST_VOTE_BILL_2", "9100002", "테스트 표결 법안 2")
    vote_bills = [existing_vote_bill, new_vote_bill]
    vote_rows_by_bill = {
        "TEST_VOTE_BILL_2": [
            _vote_row("TEST_VOTE_BILL_2", "9100002", "TEST_VOTE_MEMBER_1", "표결일", "찬성"),
            _vote_row("TEST_VOTE_BILL_2", "9100002", "TEST_VOTE_MEMBER_2", "표결이", "반대"),
            _vote_row("TEST_VOTE_BILL_2", "9100002", "TEST_VOTE_MEMBER_3", "표결삼", "기권"),
        ],
    }
    detail_calls: list[str] = []
    benchmark_output = tmp_path / "VOTES-PARALLEL-BENCHMARK.md"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, proc_result)
            VALUES ('TEST_VOTE_BILL_1', '9100001', '기존 표결 법안', '원안가결')
            """
        )
        for row in (
            _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_1", "표결일", "찬성"),
            _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_2", "표결이", "반대"),
            _vote_row("TEST_VOTE_BILL_1", "9100001", "TEST_VOTE_MEMBER_3", "표결삼", "기권"),
        ):
            cur.execute(
                """
                INSERT INTO members (mona_cd, hg_nm)
                VALUES (%s, %s)
                ON CONFLICT (mona_cd) DO NOTHING
                """,
                (row["MONA_CD"], row["HG_NM"]),
            )
            cur.execute(
                """
                INSERT INTO votes (
                    bill_id, mona_cd, vote_date, result_vote_mod,
                    poly_nm_at_vote
                )
                VALUES (%s, %s, '2026-05-07 18:16:30+09', %s, %s)
                """,
                (
                    row["BILL_ID"],
                    row["MONA_CD"],
                    row["RESULT_VOTE_MOD"],
                    row["POLY_NM"],
                ),
            )
        conn.commit()

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "AGE" not in params and endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _no_data()
        elif endpoint == "ncocpgfiaoituanbr":
            response.json.return_value = _envelope(endpoint, total=2, rows=vote_bills)
        elif endpoint == "nojepdqqaweusdfbi":
            detail_calls.append(params["BILL_ID"])
            if params["BILL_ID"] == "TEST_VOTE_BILL_1":
                raise AssertionError("existing vote rows should not be refetched")
            rows = vote_rows_by_bill[params["BILL_ID"]]
            response.json.return_value = _envelope(endpoint, total=len(rows), rows=rows)
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)

    result = ingest_votes(
        limit_pct=1.0,
        page_size=2,
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=benchmark_output,
        vote_row_fetch_mode="missing",
        vote_row_worker_count=1,
    )

    assert detail_calls == ["TEST_VOTE_BILL_2"]
    assert result.vote_row_count == 3
    assert result.upserted_votes == 3
    assert result.vote_row_skipped_bill_count == 1
    assert result.failed_vote_bill_count == 0
    assert not benchmark_output.exists()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, proc_result
            FROM bills
            WHERE bill_id = ANY(%s)
            ORDER BY bill_id
            """,
            (["TEST_VOTE_BILL_1", "TEST_VOTE_BILL_2"],),
        )
        bills = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM votes WHERE bill_id = 'TEST_VOTE_BILL_1'")
        existing_vote_count = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM votes WHERE bill_id = 'TEST_VOTE_BILL_2'")
        new_vote_count = cur.fetchone()

    assert bills == [
        ("TEST_VOTE_BILL_1", "수정가결"),
        ("TEST_VOTE_BILL_2", "원안가결"),
    ]
    assert existing_vote_count == (3,)
    assert new_vote_count == (3,)
