"""bills + bill_lead_proposers + bill_coproposers 적재.

deep module: 호출자는 `ingest_bills()` 한 함수만 알면 된다. 목록 pagination,
summary 병렬 호출, worker 측정, row 정규화, FK 검증, upsert를 내부에 숨긴다.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psycopg

from ..core.api_client import ApiResponse, fetch_endpoint_with_retry, fetch_with_age_attempts
from ..core.db import execute_many, get_conn
from ..core.endpoints import ENDPOINTS_BY_SLUG
from ..core.progress import ProgressReporter, safe_print
from ..core.throttle import cap_worker_count, cap_worker_levels
from .committee_refs import ensure_committee_refs, normalize_committee_rows
from ..ops.benchmark import (
    DEFAULT_WORKER_LEVELS,
    BenchmarkResult,
    measure_workers,
    representative_sample,
    render_parallel_benchmark,
)

BILLS_ENDPOINT = "nzmimeepazxkubdpn"
SUMMARY_ENDPOINT = "BPMBILLSUMMARY"
DEFAULT_BENCHMARK_OUTPUT = Path("docs/ops/PARALLEL-BENCHMARK.md")
SUMMARY_MAX_RETRY_RATE = 0.02
SummaryFetchMode = Literal["all", "missing"]


@dataclass(frozen=True)
class IngestBillsResult:
    """bills 적재 결과."""

    total_count: int
    target_count: int
    fetched_count: int
    upserted_bills: int
    upserted_lead_proposers: int
    upserted_coproposers: int
    ensured_member_refs: int
    selected_worker_count: int
    summary_target_count: int
    summary_skipped_count: int
    summary_success_count: int
    summary_error_count: int
    summary_retry_count: int
    summary_retried_bill_count: int
    summary_failures: tuple["BillSummaryFailure", ...]
    age_param_used: dict[str, str] | None


@dataclass(frozen=True)
class BillSummaryBackfillResult:
    """기존 bills 중 summary 결측만 채운 결과."""

    target_count: int
    updated_count: int
    no_data_count: int
    accepted_gap_count: int
    error_count: int
    retry_count: int
    retried_bill_count: int
    remaining_missing_count: int
    selected_worker_count: int
    summary_failures: tuple["BillSummaryFailure", ...]


@dataclass(frozen=True)
class BillSummaryFailure:
    """법안 summary fetch 최종 실패."""

    bill_no: str
    error: str


@dataclass(frozen=True)
class _BillListResult:
    total_count: int
    target_count: int
    rows: list[dict[str, Any]]
    age_param_used: dict[str, str] | None


@dataclass(frozen=True)
class _SummaryResult:
    summaries: dict[str, str | None]
    success_count: int
    error_count: int
    retry_count: int
    retry_item_count: int
    failures: tuple[BillSummaryFailure, ...]


@dataclass(frozen=True)
class _SummaryFetchResult:
    summary: str | None
    retry_count: int


_BILL_FIELDS: tuple[str, ...] = (
    "bill_id",
    "bill_no",
    "bill_name",
    "propose_dt",
    "proposer",
    "committee_id",
    "proc_result",
    "proc_dt",
    "law_proc_dt",
    "committee_dt",
    "cmt_proc_dt",
    "cmt_proc_result",
    "summary",
)

_API_TO_DB: dict[str, str] = {
    "BILL_ID": "bill_id",
    "BILL_NO": "bill_no",
    "BILL_NAME": "bill_name",
    "PROPOSE_DT": "propose_dt",
    "PROPOSER": "proposer",
    "COMMITTEE_ID": "committee_id",
    "PROC_RESULT": "proc_result",
    "PROC_DT": "proc_dt",
    "LAW_PROC_DT": "law_proc_dt",
    "COMMITTEE_DT": "committee_dt",
    "CMT_PROC_DT": "cmt_proc_dt",
    "CMT_PROC_RESULT_CD": "cmt_proc_result",
}

_UPSERT_BILLS_SQL = """
    INSERT INTO bills (
        bill_id, bill_no, bill_name, propose_dt,
        proposer, committee_id, proc_result, proc_dt,
        law_proc_dt, committee_dt, cmt_proc_dt, cmt_proc_result, summary
    )
    VALUES (
        %(bill_id)s, %(bill_no)s, %(bill_name)s, %(propose_dt)s,
        %(proposer)s, %(committee_id)s, %(proc_result)s, %(proc_dt)s,
        %(law_proc_dt)s, %(committee_dt)s,
        %(cmt_proc_dt)s, %(cmt_proc_result)s, %(summary)s
    )
    ON CONFLICT (bill_id) DO UPDATE SET
        bill_no            = EXCLUDED.bill_no,
        bill_name          = EXCLUDED.bill_name,
        propose_dt         = EXCLUDED.propose_dt,
        proposer           = EXCLUDED.proposer,
        committee_id       = EXCLUDED.committee_id,
        proc_result        = EXCLUDED.proc_result,
        proc_dt            = EXCLUDED.proc_dt,
        law_proc_dt        = EXCLUDED.law_proc_dt,
        committee_dt       = EXCLUDED.committee_dt,
        cmt_proc_dt        = EXCLUDED.cmt_proc_dt,
        cmt_proc_result    = EXCLUDED.cmt_proc_result,
        summary            = COALESCE(EXCLUDED.summary, bills.summary),
        fetched_at         = now()
"""

_INSERT_COPROPOSERS_SQL = """
    INSERT INTO bill_coproposers (bill_id, mona_cd, order_no)
    VALUES (%(bill_id)s, %(mona_cd)s, %(order_no)s)
    ON CONFLICT (bill_id, mona_cd) DO NOTHING
"""

_INSERT_LEAD_PROPOSERS_SQL = """
    INSERT INTO bill_lead_proposers (bill_id, mona_cd, order_no)
    VALUES (%(bill_id)s, %(mona_cd)s, %(order_no)s)
    ON CONFLICT (bill_id, mona_cd) DO NOTHING
"""

_INSERT_MEMBER_STUBS_SQL = """
    INSERT INTO members (mona_cd, hg_nm)
    VALUES (%(mona_cd)s, %(hg_nm)s)
    ON CONFLICT (mona_cd) DO NOTHING
"""

_UPDATE_MISSING_SUMMARY_SQL = """
    UPDATE bills
    SET summary = %(summary)s,
        fetched_at = now()
    WHERE bill_no = %(bill_no)s
      AND (summary IS NULL OR btrim(summary) = '')
"""


def ingest_bills(
    *,
    limit_pct: float = 0.1,
    page_size: int = 100,
    benchmark_sample_size: int = 100,
    worker_levels: tuple[int, ...] = DEFAULT_WORKER_LEVELS,
    benchmark_output_path: Path = DEFAULT_BENCHMARK_OUTPUT,
    summary_fetch_mode: SummaryFetchMode = "all",
    summary_worker_count: int | None = None,
) -> IngestBillsResult:
    """22대 법안 목록 10%와 summary를 적재한다."""
    bill_list = _fetch_bill_list(limit_pct=limit_pct, page_size=page_size)
    safe_print(
        f"[ingest-bills] target bills={bill_list.target_count}/{bill_list.total_count}",
        flush=True,
    )
    bill_nos = [str(row["BILL_NO"]) for row in bill_list.rows]
    existing_summaries = (
        _load_existing_summaries(bill_nos) if summary_fetch_mode == "missing" else {}
    )
    summary_targets = _summary_target_bill_nos(
        bill_nos,
        existing_summaries=existing_summaries,
        mode=summary_fetch_mode,
    )

    selected_worker_count, summary_result = _fetch_target_summaries(
        summary_targets,
        benchmark_sample_size=benchmark_sample_size,
        worker_levels=worker_levels,
        benchmark_output_path=benchmark_output_path,
        summary_worker_count=summary_worker_count,
    )
    summaries = {**existing_summaries, **summary_result.summaries}
    bill_rows = [
        _normalize_bill_row(row, summaries.get(str(row["BILL_NO"])))
        for row in bill_list.rows
    ]
    committee_rows = normalize_committee_rows(
        bill_list.rows,
        id_field="COMMITTEE_ID",
        name_field="COMMITTEE",
    )
    lead_proposer_rows = _normalize_lead_proposer_rows(bill_list.rows)
    coproposer_rows = _normalize_coproposer_rows(bill_list.rows)
    member_refs = _normalize_member_refs(bill_list.rows)
    bill_ids = [row["bill_id"] for row in bill_rows]

    with get_conn() as conn:
        ensured_member_refs = execute_many(conn, _INSERT_MEMBER_STUBS_SQL, member_refs)
        ensure_committee_refs(conn, committee_rows)
        _validate_member_refs(conn, bill_rows, lead_proposer_rows, coproposer_rows)
        upserted_bills = execute_many(conn, _UPSERT_BILLS_SQL, bill_rows)
        _replace_lead_proposers_for_bills(conn, bill_ids)
        upserted_lead_proposers = execute_many(
            conn,
            _INSERT_LEAD_PROPOSERS_SQL,
            lead_proposer_rows,
        )
        _replace_coproposers_for_bills(conn, bill_ids)
        upserted_coproposers = execute_many(conn, _INSERT_COPROPOSERS_SQL, coproposer_rows)
        conn.commit()

    return IngestBillsResult(
        total_count=bill_list.total_count,
        target_count=bill_list.target_count,
        fetched_count=len(bill_rows),
        upserted_bills=upserted_bills,
        upserted_lead_proposers=upserted_lead_proposers,
        upserted_coproposers=upserted_coproposers,
        ensured_member_refs=ensured_member_refs,
        selected_worker_count=selected_worker_count,
        summary_target_count=len(summary_targets),
        summary_skipped_count=len(bill_nos) - len(summary_targets),
        summary_success_count=summary_result.success_count,
        summary_error_count=summary_result.error_count,
        summary_retry_count=summary_result.retry_count,
        summary_retried_bill_count=summary_result.retry_item_count,
        summary_failures=summary_result.failures,
        age_param_used=bill_list.age_param_used,
    )


def backfill_missing_bill_summaries(
    *,
    limit: int | None = None,
    benchmark_sample_size: int = 100,
    worker_levels: tuple[int, ...] = DEFAULT_WORKER_LEVELS,
    benchmark_output_path: Path = DEFAULT_BENCHMARK_OUTPUT,
    summary_worker_count: int | None = None,
) -> BillSummaryBackfillResult:
    """이미 적재된 bills 중 summary가 NULL/공백인 법안만 BPMBILLSUMMARY로 채운다."""
    bill_nos = _load_missing_summary_bill_nos(limit=limit)
    selected_worker_count, summary_result = _fetch_target_summaries(
        bill_nos,
        benchmark_sample_size=benchmark_sample_size,
        worker_levels=worker_levels,
        benchmark_output_path=benchmark_output_path,
        summary_worker_count=summary_worker_count,
    )
    updates = [
        {"bill_no": bill_no, "summary": summary}
        for bill_no, summary in summary_result.summaries.items()
        if summary is not None
    ]
    with get_conn() as conn:
        updated_count = execute_many(conn, _UPDATE_MISSING_SUMMARY_SQL, updates)
        conn.commit()

    failed_bill_nos = {failure.bill_no for failure in summary_result.failures}
    no_data_count = sum(
        1
        for bill_no, summary in summary_result.summaries.items()
        if summary is None and bill_no not in failed_bill_nos
    )
    return BillSummaryBackfillResult(
        target_count=len(bill_nos),
        updated_count=updated_count,
        no_data_count=no_data_count,
        accepted_gap_count=no_data_count,
        error_count=summary_result.error_count,
        retry_count=summary_result.retry_count,
        retried_bill_count=summary_result.retry_item_count,
        remaining_missing_count=_count_missing_summaries(),
        selected_worker_count=selected_worker_count,
        summary_failures=summary_result.failures,
    )


def retry_bill_summary(bill_no: str) -> bool:
    """dead letter 재처리용: 단일 BILL_NO summary를 다시 가져와 반영한다."""
    result = _fetch_summary(str(bill_no))
    if result.summary is None:
        return True
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_UPDATE_MISSING_SUMMARY_SQL, {"bill_no": str(bill_no), "summary": result.summary})
        conn.commit()
    return True


def _load_missing_summary_bill_nos(*, limit: int | None = None) -> list[str]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_no
            FROM bills
            WHERE bill_no IS NOT NULL
              AND (summary IS NULL OR btrim(summary) = '')
            ORDER BY propose_dt DESC NULLS LAST, bill_no
            LIMIT %s
            """,
            (limit,),
        )
        return [str(row[0]) for row in cur.fetchall()]


def _count_missing_summaries() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM bills
            WHERE bill_no IS NOT NULL
              AND (summary IS NULL OR btrim(summary) = '')
            """
        )
        return int(cur.fetchone()[0])


def _load_existing_summaries(bill_nos: list[str]) -> dict[str, str]:
    if not bill_nos:
        return {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_no, summary
            FROM bills
            WHERE bill_no = ANY(%s)
              AND summary IS NOT NULL
              AND summary <> ''
            """,
            (bill_nos,),
        )
        return {str(bill_no): str(summary) for bill_no, summary in cur.fetchall()}


def _summary_target_bill_nos(
    bill_nos: list[str],
    *,
    existing_summaries: dict[str, str],
    mode: SummaryFetchMode,
) -> list[str]:
    if mode == "all":
        return bill_nos
    if mode == "missing":
        return [bill_no for bill_no in bill_nos if bill_no not in existing_summaries]
    raise ValueError("summary_fetch_mode must be one of: all, missing")


def _fetch_target_summaries(
    bill_nos: list[str],
    *,
    benchmark_sample_size: int,
    worker_levels: tuple[int, ...],
    benchmark_output_path: Path,
    summary_worker_count: int | None,
) -> tuple[int, _SummaryResult]:
    if not bill_nos:
        return 0, _SummaryResult(
            summaries={},
            success_count=0,
            error_count=0,
            retry_count=0,
            retry_item_count=0,
            failures=(),
        )
    if summary_worker_count is None:
        benchmark = _benchmark_summary_workers(
            representative_sample(bill_nos, benchmark_sample_size),
            worker_levels=cap_worker_levels(worker_levels),
            output_path=benchmark_output_path,
        )
        worker_count = cap_worker_count(benchmark.selected_worker_count)
    else:
        worker_count = cap_worker_count(summary_worker_count)
    return worker_count, _fetch_summaries(bill_nos, worker_count)


def _fetch_bill_list(*, limit_pct: float, page_size: int) -> _BillListResult:
    first = fetch_with_age_attempts(
        BILLS_ENDPOINT,
        ENDPOINTS_BY_SLUG[BILLS_ENDPOINT].verify_sample,
        p_index=1,
        p_size=page_size,
        sleep_between=0,
    )
    _ensure_ok(first, "bills API fetch failed")
    target_count = _target_count(first.total_count, limit_pct)
    rows = list(first.rows[:target_count])
    age_param = first.age_param_used or {}

    page = 2
    while len(rows) < target_count:
        response = fetch_endpoint_with_retry(
            BILLS_ENDPOINT,
            age_param,
            p_index=page,
            p_size=page_size,
        )
        _ensure_ok(response, f"bills API page {page} fetch failed")
        if not response.rows:
            break
        rows.extend(response.rows[: target_count - len(rows)])
        page += 1

    return _BillListResult(
        total_count=first.total_count,
        target_count=target_count,
        rows=rows,
        age_param_used=first.age_param_used,
    )


def _target_count(total_count: int, limit_pct: float) -> int:
    if limit_pct <= 0:
        raise ValueError("limit_pct must be positive")
    if limit_pct <= 1:
        return min(total_count, max(1, math.ceil(total_count * limit_pct)))
    return min(total_count, int(limit_pct))


def _benchmark_summary_workers(
    bill_nos: list[str],
    *,
    worker_levels: tuple[int, ...],
    output_path: Path,
) -> BenchmarkResult:
    benchmark = measure_workers(
        lambda bill_no, worker_count: _fetch_summary(str(bill_no)),
        items=bill_nos,
        levels=worker_levels,
        max_retry_rate=SUMMARY_MAX_RETRY_RATE,
        retry_count_from_result=lambda result: result.retry_count,
        stop_after_unacceptable_after_acceptance=True,
    )
    render_parallel_benchmark(benchmark, output_path)
    return benchmark


def _fetch_summaries(bill_nos: list[str], worker_count: int) -> _SummaryResult:
    summaries: dict[str, str | None] = {}
    failures: list[BillSummaryFailure] = []
    error_count = 0
    retry_count = 0
    retry_item_count = 0
    progress = ProgressReporter("bill summaries", len(bill_nos))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(_fetch_summary, bill_no): bill_no for bill_no in bill_nos}
        for future in as_completed(futures):
            bill_no = futures[future]
            try:
                result = future.result()
                summaries[bill_no] = result.summary
                retry_count += result.retry_count
                if result.retry_count:
                    retry_item_count += 1
                progress.advance()
            except Exception as exc:
                summaries[bill_no] = None
                error_count += 1
                failures.append(BillSummaryFailure(bill_no=bill_no, error=str(exc)))
                progress.advance(errors=1)
    progress.finish()
    return _SummaryResult(
        summaries=summaries,
        success_count=len(bill_nos) - error_count,
        error_count=error_count,
        retry_count=retry_count,
        retry_item_count=retry_item_count,
        failures=tuple(failures),
    )


def _fetch_summary(bill_no: str) -> _SummaryFetchResult:
    response = fetch_with_age_attempts(
        SUMMARY_ENDPOINT,
        {"BILL_NO": bill_no},
        p_size=10,
        sleep_between=0,
    )
    if response.status == "no_data":
        return _SummaryFetchResult(summary=None, retry_count=response.retry_count)
    _ensure_ok(response, f"summary API fetch failed for BILL_NO={bill_no}")
    if not response.rows:
        return _SummaryFetchResult(summary=None, retry_count=response.retry_count)
    return _SummaryFetchResult(
        summary=_blank_to_none(response.rows[0].get("SUMMARY")),
        retry_count=response.retry_count,
    )


def _normalize_bill_row(row: dict[str, Any], summary: str | None) -> dict[str, Any]:
    normalized = {field: None for field in _BILL_FIELDS}
    for api_field, db_field in _API_TO_DB.items():
        normalized[db_field] = _blank_to_none(row.get(api_field))
    normalized["summary"] = summary

    if not normalized["bill_id"]:
        raise ValueError("bills API row missing BILL_ID")
    if not normalized["bill_no"]:
        raise ValueError(f"bills API row missing BILL_NO: {normalized['bill_id']}")
    if not normalized["bill_name"]:
        raise ValueError(f"bills API row missing BILL_NAME: {normalized['bill_id']}")
    return normalized


def _normalize_lead_proposer_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lead_proposers: list[dict[str, Any]] = []
    for row in rows:
        bill_id = _blank_to_none(row.get("BILL_ID"))
        if not bill_id:
            continue
        for order_no, mona_cd in enumerate(_split_mona_codes(row.get("RST_MONA_CD")), 1):
            lead_proposers.append(
                {"bill_id": bill_id, "mona_cd": mona_cd, "order_no": order_no}
            )
    return lead_proposers


def _normalize_coproposer_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coproposers: list[dict[str, Any]] = []
    for row in rows:
        bill_id = _blank_to_none(row.get("BILL_ID"))
        if not bill_id:
            continue
        for order_no, mona_cd in enumerate(_split_mona_codes(row.get("PUBL_MONA_CD")), 1):
            coproposers.append(
                {"bill_id": bill_id, "mona_cd": mona_cd, "order_no": order_no}
            )
    return coproposers


def _split_mona_codes(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize_member_refs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names_by_code: dict[str, str] = {}
    for row in rows:
        names_by_code.update(
            _member_names_from_codes(row.get("RST_MONA_CD"), row.get("RST_PROPOSER"))
        )
        names_by_code.update(
            _member_names_from_codes(row.get("PUBL_MONA_CD"), row.get("PUBL_PROPOSER"))
        )
    return [
        {"mona_cd": mona_cd, "hg_nm": hg_nm}
        for mona_cd, hg_nm in sorted(names_by_code.items())
    ]


def _member_names_from_codes(codes_value: Any, names_value: Any) -> dict[str, str]:
    codes = _split_mona_codes(codes_value)
    names = _split_names(names_value)
    result: dict[str, str] = {}
    for index, code in enumerate(codes):
        name = names[index] if index < len(names) else code
        result[code] = name or code
    return result


def _split_names(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _validate_member_refs(
    conn: psycopg.Connection,
    bill_rows: list[dict[str, Any]],
    lead_proposer_rows: list[dict[str, Any]],
    coproposer_rows: list[dict[str, Any]],
) -> None:
    referenced = {
        row["mona_cd"]
        for row in lead_proposer_rows
        if row.get("mona_cd")
    } | {
        row["mona_cd"]
        for row in coproposer_rows
        if row.get("mona_cd")
    }
    if not referenced:
        return

    with conn.cursor() as cur:
        cur.execute("SELECT mona_cd FROM members WHERE mona_cd = ANY(%s)", (list(referenced),))
        existing = {row[0] for row in cur.fetchall()}
    missing = sorted(referenced - existing)
    if missing:
        sample = ", ".join(missing[:10])
        raise RuntimeError(f"members FK missing for bills ingest: {sample}")


def _replace_lead_proposers_for_bills(conn: psycopg.Connection, bill_ids: list[str]) -> None:
    if not bill_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bill_lead_proposers WHERE bill_id = ANY(%s)", (bill_ids,))


def _replace_coproposers_for_bills(conn: psycopg.Connection, bill_ids: list[str]) -> None:
    if not bill_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM bill_coproposers WHERE bill_id = ANY(%s)", (bill_ids,))


def _ensure_ok(response: ApiResponse, message: str) -> None:
    if response.status != "ok":
        detail = response.error or response.status
        raise RuntimeError(f"{message}: {detail}")


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value
