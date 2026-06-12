"""ALLBILL final outcome backfill behavior."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from congress_db.core.api_client import ApiResponse
from congress_db.core.db import get_conn
from congress_db.ingest.backfill import run_staged_ingest
from congress_db.ingest.bill_final_outcomes import backfill_bill_final_outcomes
from scripts.backfill_bill_final_outcomes import build_bill_final_outcomes_stage

TEST_BILLS = {
    "TEST_FINAL_2218526": "2998526",
    "TEST_FINAL_PROPOSE_NULL": "2991001",
    "TEST_FINAL_PROPOSE_PRESENT": "2991002",
    "TEST_FINAL_UNPROMULGATED": "2991003",
    "TEST_FINAL_LAW_PROC": "2991004",
    "TEST_FINAL_IDEMPOTENT": "2991005",
    "TEST_FINAL_NO_DATA": "2991006",
}


def setup_function() -> None:
    _delete_test_rows()


def teardown_function() -> None:
    _delete_test_rows()


def _delete_test_rows() -> None:
    bill_ids = list(TEST_BILLS.keys())
    bill_nos = list(TEST_BILLS.values())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM bill_final_outcomes WHERE bill_no = ANY(%s)", (bill_nos,))
        cur.execute(
            """
            DELETE FROM dead_letters
            WHERE source = 'bill_final_outcomes'
              AND item_key = ANY(%s)
            """,
            (bill_nos,),
        )
        cur.execute(
            """
            DELETE FROM ingest_runs
            WHERE summary->>'entrypoint' = 'test_bill_final_outcomes'
            """
        )
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (bill_ids,))
        conn.commit()


def _insert_bill(
    bill_id: str,
    bill_no: str,
    *,
    proc_result: str | None = "원안가결",
    propose_dt: str | None = None,
    law_proc_dt: str | None = None,
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (
                bill_id, bill_no, bill_name, proc_result, propose_dt, law_proc_dt
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (bill_id, bill_no, bill_id, proc_result, propose_dt, law_proc_dt),
        )
        conn.commit()


def _allbill_row(
    bill_no: str,
    *,
    ppsl_dt: str | None = "2026-04-22",
    rgs_rsln_dt: str | None = "2026-04-23",
    gvrn_trsf_dt: str | None = "2026-04-30",
    prom_dt: str | None = "2026-05-12",
    prom_no: str | None = "21634",
    prom_law_nm: str | None = "전세사기피해자 지원 및 주거안정에 관한 특별법",
) -> dict[str, Any]:
    return {
        "ERACO": "제22대",
        "BILL_ID": f"PRC_TEST_{bill_no}",
        "BILL_NO": bill_no,
        "BILL_KND": "법률안",
        "BILL_NM": "테스트 법안",
        "PPSR_KND": "위원장",
        "PPSR_NM": "테스트",
        "PPSL_SESS": "제22대",
        "PPSL_DT": ppsl_dt,
        "JRCMIT_NM": "테스트위원회",
        "JRCMIT_CMMT_DT": None,
        "JRCMIT_PRSNT_DT": None,
        "JRCMIT_PROC_DT": None,
        "JRCMIT_PROC_RSLT": None,
        "LAW_CMMT_DT": None,
        "LAW_PRSNT_DT": None,
        "LAW_PROC_DT": None,
        "LAW_PROC_RSLT": None,
        "RGS_PRSNT_DT": None,
        "RGS_RSLN_DT": rgs_rsln_dt,
        "RGS_CONF_NM": "본회의",
        "RGS_CONF_RSLT": "가결",
        "GVRN_TRSF_DT": gvrn_trsf_dt,
        "PROM_LAW_NM": prom_law_nm,
        "PROM_DT": prom_dt,
        "PROM_NO": prom_no,
        "LINK_URL": "https://likms.assembly.go.kr/bill/billDetail.do?billId=PRC_TEST",
    }


def _mock_fetcher(
    responses_by_bill_no: dict[str, ApiResponse],
) -> tuple[Callable[..., ApiResponse], list[str]]:
    calls: list[str] = []

    def fetch(endpoint: str, params: dict[str, str] | None = None, **_: Any) -> ApiResponse:
        assert endpoint == "ALLBILL"
        assert params is not None
        bill_no = params["BILL_NO"]
        calls.append(bill_no)
        return responses_by_bill_no[bill_no]

    return fetch, calls


def _ok(row: dict[str, Any]) -> ApiResponse:
    return ApiResponse(status="ok", total_count=1, rows=[row])


def test_allbill_row_maps_to_bill_final_outcomes() -> None:
    bill_no = TEST_BILLS["TEST_FINAL_2218526"]
    _insert_bill("TEST_FINAL_2218526", bill_no)
    fetch, _calls = _mock_fetcher({bill_no: _ok(_allbill_row(bill_no))})

    result = backfill_bill_final_outcomes(fetch_allbill=fetch, bill_nos=(bill_no,))

    assert result.outcome_upserted_count == 1
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_no, plenary_dt, govt_transfer_dt, promulgation_dt,
                   prom_no, prom_law_nm
            FROM bill_final_outcomes
            WHERE bill_no = %s
            """,
            (bill_no,),
        )
        row = cur.fetchone()

    assert row == (
        bill_no,
        date(2026, 4, 23),
        date(2026, 4, 30),
        date(2026, 5, 12),
        "21634",
        "전세사기피해자 지원 및 주거안정에 관한 특별법",
    )


def test_propose_dt_backfill_fills_null_and_preserves_existing_value() -> None:
    null_bill_no = TEST_BILLS["TEST_FINAL_PROPOSE_NULL"]
    present_bill_no = TEST_BILLS["TEST_FINAL_PROPOSE_PRESENT"]
    _insert_bill("TEST_FINAL_PROPOSE_NULL", null_bill_no, proc_result=None)
    _insert_bill(
        "TEST_FINAL_PROPOSE_PRESENT",
        present_bill_no,
        propose_dt="2024-01-01",
    )
    fetch, _calls = _mock_fetcher(
        {
            null_bill_no: _ok(_allbill_row(null_bill_no, ppsl_dt="2026-04-22")),
            present_bill_no: _ok(_allbill_row(present_bill_no, ppsl_dt="2026-05-01")),
        }
    )

    result = backfill_bill_final_outcomes(
        fetch_allbill=fetch,
        bill_nos=(null_bill_no, present_bill_no),
    )

    assert result.propose_dt_updated_count == 1
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_no, propose_dt
            FROM bills
            WHERE bill_no = ANY(%s)
            ORDER BY bill_no
            """,
            ([null_bill_no, present_bill_no],),
        )
        rows = cur.fetchall()

    assert rows == [
        (null_bill_no, date(2026, 4, 22)),
        (present_bill_no, date(2024, 1, 1)),
    ]


def test_unpromulgated_allbill_row_keeps_null_promulgation_and_counts_gap() -> None:
    bill_no = TEST_BILLS["TEST_FINAL_UNPROMULGATED"]
    _insert_bill("TEST_FINAL_UNPROMULGATED", bill_no)
    fetch, _calls = _mock_fetcher(
        {
            bill_no: _ok(
                _allbill_row(
                    bill_no,
                    prom_dt=None,
                    prom_no=None,
                    prom_law_nm=None,
                )
            )
        }
    )

    result = backfill_bill_final_outcomes(fetch_allbill=fetch, bill_nos=(bill_no,))

    assert result.accepted_gap_count == 1
    assert result.error_count == 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT promulgation_dt, prom_no, prom_law_nm
            FROM bill_final_outcomes
            WHERE bill_no = %s
            """,
            (bill_no,),
        )
        row = cur.fetchone()

    assert row == (None, None, None)


def test_law_proc_dt_is_not_changed_by_allbill_backfill() -> None:
    bill_no = TEST_BILLS["TEST_FINAL_LAW_PROC"]
    _insert_bill("TEST_FINAL_LAW_PROC", bill_no, law_proc_dt="2025-01-02")
    fetch, _calls = _mock_fetcher({bill_no: _ok(_allbill_row(bill_no))})

    backfill_bill_final_outcomes(fetch_allbill=fetch, bill_nos=(bill_no,))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT law_proc_dt FROM bills WHERE bill_no = %s", (bill_no,))
        law_proc_dt = cur.fetchone()[0]

    assert law_proc_dt == date(2025, 1, 2)


def test_bill_final_outcomes_backfill_is_idempotent() -> None:
    bill_no = TEST_BILLS["TEST_FINAL_IDEMPOTENT"]
    _insert_bill("TEST_FINAL_IDEMPOTENT", bill_no)
    fetch, calls = _mock_fetcher({bill_no: _ok(_allbill_row(bill_no))})

    first = backfill_bill_final_outcomes(fetch_allbill=fetch, bill_nos=(bill_no,))
    second = backfill_bill_final_outcomes(fetch_allbill=fetch, bill_nos=(bill_no,))

    assert first.outcome_upserted_count == 1
    assert first.propose_dt_updated_count == 1
    assert second.skipped_count == 1
    assert second.outcome_upserted_count == 0
    assert calls == [bill_no]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM bill_final_outcomes WHERE bill_no = %s", (bill_no,))
        outcome_count = cur.fetchone()[0]

    assert outcome_count == 1


def test_no_data_records_dead_letter_through_backfill_stage() -> None:
    bill_no = TEST_BILLS["TEST_FINAL_NO_DATA"]
    _insert_bill("TEST_FINAL_NO_DATA", bill_no)
    fetch, _calls = _mock_fetcher(
        {bill_no: ApiResponse(status="no_data", total_count=0)}
    )

    stage = build_bill_final_outcomes_stage(fetch_allbill=fetch, bill_nos=(bill_no,))
    run = run_staged_ingest(
        mode="backfill",
        stages=(stage,),
        run_metadata={"entrypoint": "test_bill_final_outcomes"},
    )

    assert run.status == "degraded_success"
    assert run.dead_letter_count == 1
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source, stage, item_key, status
            FROM dead_letters
            WHERE source = 'bill_final_outcomes'
              AND item_key = %s
            """,
            (bill_no,),
        )
        row = cur.fetchone()

    assert row == ("bill_final_outcomes", "fetch", bill_no, "pending")
