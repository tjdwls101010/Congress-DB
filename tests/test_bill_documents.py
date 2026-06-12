"""BILLRCPV2 bill_documents backfill behavior."""

from __future__ import annotations

from typing import Any, Callable

from congress_db.core.api_client import ApiResponse
from congress_db.core.db import get_conn
from congress_db.ingest.backfill import run_staged_ingest
from congress_db.ingest.bill_documents import backfill_bill_documents
from scripts.backfill_bill_documents import build_bill_documents_stage

TEST_BILLS = {
    "TEST_DOC_BOOK_ONLY": "2992001",
    "TEST_DOC_BOOK_COST": "2992002",
    "TEST_DOC_NO_DATA": "2992003",
    "TEST_DOC_IDEMPOTENT": "2992004",
}


def setup_function() -> None:
    _delete_test_rows()


def teardown_function() -> None:
    _delete_test_rows()


def _delete_test_rows() -> None:
    bill_ids = list(TEST_BILLS.keys())
    bill_nos = list(TEST_BILLS.values())
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM bill_documents WHERE bill_no = ANY(%s)", (bill_nos,))
        cur.execute(
            """
            DELETE FROM dead_letters
            WHERE source = 'bill_documents'
              AND item_key = ANY(%s)
            """,
            (bill_ids,),
        )
        cur.execute(
            """
            DELETE FROM ingest_runs
            WHERE summary->>'entrypoint' = 'test_bill_documents'
            """
        )
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (bill_ids,))
        conn.commit()


def _insert_bill(bill_id: str, bill_no: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, propose_dt)
            VALUES (%s, %s, %s, '2999-01-01')
            """,
            (bill_id, bill_no, bill_id),
        )
        conn.commit()


def _billrcpv2_row(
    bill_id: str,
    *,
    book_hwp_url: str | None = "https://likms.assembly.go.kr/file/book.hwp",
    book_pdf_url: str | None = "https://likms.assembly.go.kr/file/book.pdf",
    cost_hwp_url: str | None = None,
    cost_pdf_url: str | None = None,
    link_url: str | None = "https://likms.assembly.go.kr/bill/billDetail.do",
) -> dict[str, Any]:
    return {
        "BILL_ID": bill_id,
        "BOOK_HWPURL": book_hwp_url,
        "BOOK_PDFURL": book_pdf_url,
        "COST_HWPURL": cost_hwp_url,
        "COST_PDFURL": cost_pdf_url,
        "LINK_URL": link_url,
    }


def _mock_fetcher(
    responses_by_bill_id: dict[str, ApiResponse],
) -> tuple[Callable[..., ApiResponse], list[str]]:
    calls: list[str] = []

    def fetch(endpoint: str, params: dict[str, str] | None = None, **_: Any) -> ApiResponse:
        assert endpoint == "BILLRCPV2"
        assert params is not None
        bill_id = params["BILL_ID"]
        calls.append(bill_id)
        return responses_by_bill_id[bill_id]

    return fetch, calls


def _ok(row: dict[str, Any]) -> ApiResponse:
    return ApiResponse(status="ok", total_count=1, rows=[row])


def test_book_urls_create_bill_text_document_only() -> None:
    bill_id = "TEST_DOC_BOOK_ONLY"
    bill_no = TEST_BILLS[bill_id]
    _insert_bill(bill_id, bill_no)
    fetch, calls = _mock_fetcher({bill_id: _ok(_billrcpv2_row(bill_id))})

    result = backfill_bill_documents(fetch_billrcpv2=fetch, bill_ids=(bill_id,))

    assert calls == [bill_id]
    assert result.document_upserted_count == 1
    assert result.bill_text_count == 1
    assert result.cost_estimate_count == 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_no, source, source_bill_id, document_kind,
                   hwp_url, pdf_url, link_url, parse_status
            FROM bill_documents
            WHERE bill_no = %s
            """,
            (bill_no,),
        )
        rows = cur.fetchall()

    assert rows == [
        (
            bill_no,
            "billrcpv2",
            bill_id,
            "bill_text",
            "https://likms.assembly.go.kr/file/book.hwp",
            "https://likms.assembly.go.kr/file/book.pdf",
            "https://likms.assembly.go.kr/bill/billDetail.do",
            "not_parsed",
        )
    ]


def test_book_and_cost_urls_create_two_document_rows() -> None:
    bill_id = "TEST_DOC_BOOK_COST"
    bill_no = TEST_BILLS[bill_id]
    _insert_bill(bill_id, bill_no)
    fetch, _calls = _mock_fetcher(
        {
            bill_id: _ok(
                _billrcpv2_row(
                    bill_id,
                    cost_hwp_url="https://likms.assembly.go.kr/file/cost.hwp",
                    cost_pdf_url="https://likms.assembly.go.kr/file/cost.pdf",
                )
            )
        }
    )

    result = backfill_bill_documents(fetch_billrcpv2=fetch, bill_ids=(bill_id,))

    assert result.document_upserted_count == 2
    assert result.bill_text_count == 1
    assert result.cost_estimate_count == 1
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT document_kind, hwp_url, pdf_url, link_url, parse_status
            FROM bill_documents
            WHERE bill_no = %s
            ORDER BY document_kind
            """,
            (bill_no,),
        )
        rows = cur.fetchall()

    assert rows == [
        (
            "bill_text",
            "https://likms.assembly.go.kr/file/book.hwp",
            "https://likms.assembly.go.kr/file/book.pdf",
            "https://likms.assembly.go.kr/bill/billDetail.do",
            "not_parsed",
        ),
        (
            "cost_estimate",
            "https://likms.assembly.go.kr/file/cost.hwp",
            "https://likms.assembly.go.kr/file/cost.pdf",
            "https://likms.assembly.go.kr/bill/billDetail.do",
            "not_parsed",
        ),
    ]


def test_no_data_records_dead_letter_through_backfill_stage() -> None:
    bill_id = "TEST_DOC_NO_DATA"
    bill_no = TEST_BILLS[bill_id]
    _insert_bill(bill_id, bill_no)
    fetch, _calls = _mock_fetcher(
        {bill_id: ApiResponse(status="no_data", total_count=0)}
    )

    stage = build_bill_documents_stage(fetch_billrcpv2=fetch, bill_ids=(bill_id,))
    run = run_staged_ingest(
        mode="backfill",
        stages=(stage,),
        run_metadata={"entrypoint": "test_bill_documents"},
    )

    assert run.status == "degraded_success"
    assert run.dead_letter_count == 1
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source, stage, item_key, status
            FROM dead_letters
            WHERE source = 'bill_documents'
              AND item_key = %s
            """,
            (bill_id,),
        )
        row = cur.fetchone()

    assert row == ("bill_documents", "fetch", bill_id, "pending")


def test_bill_documents_backfill_is_idempotent() -> None:
    bill_id = "TEST_DOC_IDEMPOTENT"
    bill_no = TEST_BILLS[bill_id]
    _insert_bill(bill_id, bill_no)
    fetch, calls = _mock_fetcher({bill_id: _ok(_billrcpv2_row(bill_id))})

    first = backfill_bill_documents(fetch_billrcpv2=fetch, bill_ids=(bill_id,))
    second = backfill_bill_documents(fetch_billrcpv2=fetch, bill_ids=(bill_id,))

    assert first.document_upserted_count == 1
    assert second.document_upserted_count == 1
    assert calls == [bill_id, bill_id]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM bill_documents WHERE bill_no = %s", (bill_no,))
        document_count = cur.fetchone()[0]

    assert document_count == 1
