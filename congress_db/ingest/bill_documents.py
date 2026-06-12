"""BILLRCPV2 법안 문서 URL inventory 백필."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..core.api_client import ApiResponse, fetch_endpoint
from ..core.db import execute_many, get_conn
from ..core.progress import ProgressReporter

BILL_DOCUMENTS_ENDPOINT = "BILLRCPV2"
BILL_DOCUMENTS_SOURCE = "billrcpv2"
BILL_TEXT = "bill_text"
COST_ESTIMATE = "cost_estimate"
NOT_PARSED = "not_parsed"

FetchBillDocuments = Callable[..., ApiResponse]


@dataclass(frozen=True)
class BillDocumentTarget:
    """BILLRCPV2 조회 대상 법안."""

    bill_id: str
    bill_no: str


@dataclass(frozen=True)
class BillDocumentFailure:
    """BILLRCPV2 단일 BILL_ID 조회 실패."""

    bill_id: str
    bill_no: str
    reason: str
    error: str


@dataclass(frozen=True)
class BillDocumentsBackfillResult:
    """BILLRCPV2 문서 URL inventory 백필 결과."""

    target_count: int
    fetch_target_count: int
    fetched_count: int
    document_upserted_count: int
    bill_text_count: int
    cost_estimate_count: int
    no_data_count: int
    error_count: int
    failures: tuple[BillDocumentFailure, ...]


@dataclass(frozen=True)
class _FetchedBillDocumentRow:
    target: BillDocumentTarget
    row: dict[str, Any]


_UPSERT_DOCUMENT_SQL = """
    INSERT INTO bill_documents (
        bill_no, source, source_bill_id, document_kind,
        hwp_url, pdf_url, link_url, parse_status
    )
    VALUES (
        %(bill_no)s, %(source)s, %(source_bill_id)s, %(document_kind)s,
        %(hwp_url)s, %(pdf_url)s, %(link_url)s, %(parse_status)s
    )
    ON CONFLICT (bill_no, document_kind) DO UPDATE SET
        source         = EXCLUDED.source,
        source_bill_id = EXCLUDED.source_bill_id,
        hwp_url        = EXCLUDED.hwp_url,
        pdf_url        = EXCLUDED.pdf_url,
        link_url       = EXCLUDED.link_url,
        parse_status   = EXCLUDED.parse_status,
        fetched_at     = now()
"""


def backfill_bill_documents(
    *,
    limit: int | None = None,
    bill_ids: Sequence[str] | None = None,
    fetch_billrcpv2: FetchBillDocuments = fetch_endpoint,
) -> BillDocumentsBackfillResult:
    """BILLRCPV2를 BILL_ID별로 조회해 bill_documents URL inventory를 채운다."""
    targets = _load_targets(bill_ids=bill_ids)
    fetch_targets = targets
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        fetch_targets = targets[:limit]

    fetched, failures = _fetch_bill_document_rows(
        fetch_targets,
        fetch_billrcpv2=fetch_billrcpv2,
    )
    document_rows: list[dict[str, Any]] = []
    normalization_failures: list[BillDocumentFailure] = []
    for item in fetched:
        rows = _normalize_document_rows(item.target, item.row)
        if rows:
            document_rows.extend(rows)
            continue
        normalization_failures.append(
            BillDocumentFailure(
                bill_id=item.target.bill_id,
                bill_no=item.target.bill_no,
                reason="no_document_urls",
                error="BILLRCPV2 returned no BOOK or COST document URLs",
            )
        )

    with get_conn() as conn:
        document_upserted_count = execute_many(conn, _UPSERT_DOCUMENT_SQL, document_rows)
        conn.commit()

    all_failures = tuple(failures + normalization_failures)
    no_data_count = sum(1 for failure in all_failures if failure.reason == "no_data")
    error_count = len(all_failures) - no_data_count

    return BillDocumentsBackfillResult(
        target_count=len(targets),
        fetch_target_count=len(fetch_targets),
        fetched_count=len(fetched),
        document_upserted_count=document_upserted_count,
        bill_text_count=sum(1 for row in document_rows if row["document_kind"] == BILL_TEXT),
        cost_estimate_count=sum(
            1 for row in document_rows if row["document_kind"] == COST_ESTIMATE
        ),
        no_data_count=no_data_count,
        error_count=error_count,
        failures=all_failures,
    )


def _load_targets(*, bill_ids: Sequence[str] | None = None) -> list[BillDocumentTarget]:
    selected_bill_ids = _selected_bill_ids(bill_ids)
    if bill_ids is not None and not selected_bill_ids:
        return []

    filter_sql = ""
    params: list[object] = []
    if selected_bill_ids is not None:
        filter_sql = "WHERE b.bill_id = ANY(%s)"
        params.append(selected_bill_ids)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT b.bill_id, b.bill_no
            FROM bills b
            {filter_sql}
            ORDER BY b.propose_dt ASC NULLS FIRST, b.bill_no
            """,
            params,
        )
        return [
            BillDocumentTarget(
                bill_id=str(row[0]),
                bill_no=str(row[1]),
            )
            for row in cur.fetchall()
        ]


def _selected_bill_ids(bill_ids: Sequence[str] | None) -> list[str] | None:
    if bill_ids is None:
        return None
    return sorted({str(bill_id).strip() for bill_id in bill_ids if str(bill_id).strip()})


def _fetch_bill_document_rows(
    targets: Sequence[BillDocumentTarget],
    *,
    fetch_billrcpv2: FetchBillDocuments,
) -> tuple[list[_FetchedBillDocumentRow], list[BillDocumentFailure]]:
    fetched: list[_FetchedBillDocumentRow] = []
    failures: list[BillDocumentFailure] = []
    progress = ProgressReporter("BILLRCPV2 bill documents", len(targets))
    progress.start()
    for target in targets:
        response = fetch_billrcpv2(BILL_DOCUMENTS_ENDPOINT, {"BILL_ID": target.bill_id})
        if response.status == "ok" and response.rows:
            fetched.append(_FetchedBillDocumentRow(target=target, row=dict(response.rows[0])))
            progress.advance()
            continue
        if response.status == "no_data":
            failures.append(
                BillDocumentFailure(
                    bill_id=target.bill_id,
                    bill_no=target.bill_no,
                    reason="no_data",
                    error="BILLRCPV2 returned no data",
                )
            )
            progress.advance(errors=1)
            continue
        if response.status == "ok" and not response.rows:
            failures.append(
                BillDocumentFailure(
                    bill_id=target.bill_id,
                    bill_no=target.bill_no,
                    reason="no_data",
                    error="BILLRCPV2 returned empty rows",
                )
            )
            progress.advance(errors=1)
            continue
        failures.append(
            BillDocumentFailure(
                bill_id=target.bill_id,
                bill_no=target.bill_no,
                reason="fetch_error",
                error=response.error or "BILLRCPV2 fetch failed",
            )
        )
        progress.advance(errors=1)
    progress.finish()
    return fetched, failures


def _normalize_document_rows(
    target: BillDocumentTarget,
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    link_url = _blank_to_none(row.get("LINK_URL"))
    rows: list[dict[str, Any]] = []
    book_hwp_url = _blank_to_none(row.get("BOOK_HWPURL"))
    book_pdf_url = _blank_to_none(row.get("BOOK_PDFURL"))
    if book_hwp_url is not None or book_pdf_url is not None:
        rows.append(
            _document_row(
                target,
                document_kind=BILL_TEXT,
                hwp_url=book_hwp_url,
                pdf_url=book_pdf_url,
                link_url=link_url,
            )
        )

    cost_hwp_url = _blank_to_none(row.get("COST_HWPURL"))
    cost_pdf_url = _blank_to_none(row.get("COST_PDFURL"))
    if cost_hwp_url is not None or cost_pdf_url is not None:
        rows.append(
            _document_row(
                target,
                document_kind=COST_ESTIMATE,
                hwp_url=cost_hwp_url,
                pdf_url=cost_pdf_url,
                link_url=link_url,
            )
        )

    return rows


def _document_row(
    target: BillDocumentTarget,
    *,
    document_kind: str,
    hwp_url: str | None,
    pdf_url: str | None,
    link_url: str | None,
) -> dict[str, Any]:
    return {
        "bill_no": target.bill_no,
        "source": BILL_DOCUMENTS_SOURCE,
        "source_bill_id": target.bill_id,
        "document_kind": document_kind,
        "hwp_url": hwp_url,
        "pdf_url": pdf_url,
        "link_url": link_url,
        "parse_status": NOT_PARSED,
    }


def _blank_to_none(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value
