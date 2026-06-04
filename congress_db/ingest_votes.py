"""votes 테이블 적재."""

from __future__ import annotations

import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .api_client import ApiResponse, fetch_endpoint_with_retry, fetch_with_age_attempts
from .benchmark import (
    DEFAULT_WORKER_LEVELS,
    measure_workers,
    representative_sample,
    render_parallel_benchmark,
)
from .db import execute_many, get_conn
from .endpoints import ENDPOINTS_BY_SLUG
from .progress import ProgressReporter, safe_print

VOTE_BILL_ENDPOINT = "ncocpgfiaoituanbr"
VOTE_ROWS_ENDPOINT = "nojepdqqaweusdfbi"
SEOUL = ZoneInfo("Asia/Seoul")
DEFAULT_VOTE_BENCHMARK_OUTPUT = Path("docs/VOTES-PARALLEL-BENCHMARK.md")
DEFAULT_VOTE_ROW_RETRY_DELAYS = (1.0, 4.0, 16.0)


@dataclass(frozen=True)
class IngestVotesResult:
    """votes 적재 결과."""

    total_bill_count: int
    target_bill_count: int
    vote_bill_count: int
    vote_row_count: int
    upserted_bill_refs: int
    ensured_member_refs: int
    upserted_votes: int
    selected_worker_count: int
    tolerated_distribution_mismatches: int
    failed_vote_bill_count: int
    vote_row_failures: tuple["VoteRowFailure", ...]
    age_param_used: dict[str, str] | None


@dataclass(frozen=True)
class _VoteBillListResult:
    total_count: int
    target_count: int
    rows: list[dict[str, Any]]
    age_param_used: dict[str, str] | None


@dataclass(frozen=True)
class VoteRowFailure:
    """본회의 표결 상세 row 최종 실패."""

    bill_id: str
    error: str
    attempts: int


@dataclass(frozen=True)
class _VoteRowsFetchResult:
    rows_by_bill: dict[str, list[dict[str, Any]]]
    failures: tuple[VoteRowFailure, ...]


_UPSERT_BILL_REFS_SQL = """
    INSERT INTO bills (
        bill_id, bill_no, bill_name, committee, committee_id,
        proc_result, proc_dt, detail_link, age
    )
    VALUES (
        %(bill_id)s, %(bill_no)s, %(bill_name)s, %(committee)s, %(committee_id)s,
        %(proc_result)s, %(proc_dt)s, %(detail_link)s, %(age)s
    )
    ON CONFLICT (bill_id) DO UPDATE SET
        bill_no      = EXCLUDED.bill_no,
        bill_name    = EXCLUDED.bill_name,
        committee    = COALESCE(EXCLUDED.committee, bills.committee),
        committee_id = COALESCE(EXCLUDED.committee_id, bills.committee_id),
        proc_result  = COALESCE(EXCLUDED.proc_result, bills.proc_result),
        proc_dt      = COALESCE(EXCLUDED.proc_dt, bills.proc_dt),
        detail_link  = COALESCE(EXCLUDED.detail_link, bills.detail_link),
        age          = EXCLUDED.age,
        fetched_at   = now()
"""

_INSERT_MEMBER_REFS_SQL = """
    INSERT INTO members (mona_cd, hg_nm)
    VALUES (%(mona_cd)s, %(hg_nm)s)
    ON CONFLICT (mona_cd) DO NOTHING
"""

_UPSERT_VOTES_SQL = """
    INSERT INTO votes (
        bill_id, mona_cd, vote_date, result_vote_mod,
        poly_nm_at_vote, session_cd, currents_cd
    )
    VALUES (
        %(bill_id)s, %(mona_cd)s, %(vote_date)s, %(result_vote_mod)s,
        %(poly_nm_at_vote)s, %(session_cd)s, %(currents_cd)s
    )
    ON CONFLICT (bill_id, mona_cd) DO UPDATE SET
        vote_date       = EXCLUDED.vote_date,
        result_vote_mod = EXCLUDED.result_vote_mod,
        poly_nm_at_vote = EXCLUDED.poly_nm_at_vote,
        session_cd      = EXCLUDED.session_cd,
        currents_cd     = EXCLUDED.currents_cd
"""


def ingest_votes(
    *,
    limit_pct: float = 0.1,
    page_size: int = 100,
    benchmark_sample_size: int = 100,
    worker_levels: tuple[int, ...] = DEFAULT_WORKER_LEVELS,
    benchmark_output_path: Path = DEFAULT_VOTE_BENCHMARK_OUTPUT,
    retry_delays: tuple[float, ...] = DEFAULT_VOTE_ROW_RETRY_DELAYS,
    allow_partial: bool = False,
) -> IngestVotesResult:
    """22대 본회의 표결 10%를 votes에 적재한다."""
    vote_bill_list = _fetch_vote_bill_list(limit_pct=limit_pct, page_size=page_size)
    safe_print(
        "[ingest-votes] target vote bills="
        f"{vote_bill_list.target_count}/{vote_bill_list.total_count}",
        flush=True,
    )
    bill_ids = [str(row["BILL_ID"]) for row in vote_bill_list.rows]
    benchmark = measure_workers(
        lambda bill_id, worker_count: _fetch_vote_rows_with_retry(
            str(bill_id),
            retry_delays=retry_delays,
        ),
        items=representative_sample(bill_ids, benchmark_sample_size),
        levels=worker_levels,
    )
    render_parallel_benchmark(benchmark, benchmark_output_path)
    fetch_result = _fetch_vote_rows_for_bills(
        bill_ids,
        worker_count=benchmark.selected_worker_count,
        retry_delays=retry_delays,
    )
    vote_rows_by_bill = dict(fetch_result.rows_by_bill)
    vote_row_failures = fetch_result.failures
    if vote_row_failures:
        retry_result = _retry_failed_vote_bills(
            vote_row_failures,
            selected_worker_count=benchmark.selected_worker_count,
            retry_delays=retry_delays,
        )
        vote_rows_by_bill.update(retry_result.rows_by_bill)
        vote_row_failures = retry_result.failures
    if vote_row_failures and not allow_partial:
        sample = "; ".join(
            f"{failure.bill_id}: attempts={failure.attempts} {failure.error}"
            for failure in vote_row_failures[:5]
        )
        raise RuntimeError(
            "vote row ingest finished with persistent fetch failures: "
            f"errors={len(vote_row_failures)} sample={sample}"
        )

    tolerated_distribution_mismatches = 0
    for vote_bill in vote_bill_list.rows:
        source_bill_id = str(vote_bill["BILL_ID"])
        if source_bill_id not in vote_rows_by_bill:
            continue
        matched = _validate_vote_distribution(
            vote_bill,
            vote_rows_by_bill[source_bill_id],
        )
        if not matched:
            tolerated_distribution_mismatches += 1

    canonical_bill_ids = _load_canonical_bill_ids(vote_bill_list.rows)
    bill_refs = [
        _normalize_bill_ref(
            row,
            bill_id=canonical_bill_ids[str(row["BILL_ID"])],
        )
        for row in vote_bill_list.rows
    ]
    member_refs = _normalize_member_refs(vote_rows_by_bill)
    vote_rows = [
        _normalize_vote_row(row, bill_id=canonical_bill_ids[source_bill_id])
        for source_bill_id, rows in vote_rows_by_bill.items()
        for row in rows
    ]

    with get_conn() as conn:
        upserted_bill_refs = execute_many(conn, _UPSERT_BILL_REFS_SQL, bill_refs)
        ensured_member_refs = execute_many(conn, _INSERT_MEMBER_REFS_SQL, member_refs)
        upserted_votes = execute_many(conn, _UPSERT_VOTES_SQL, vote_rows)
        conn.commit()

    return IngestVotesResult(
        total_bill_count=vote_bill_list.total_count,
        target_bill_count=vote_bill_list.target_count,
        vote_bill_count=len(vote_bill_list.rows),
        vote_row_count=len(vote_rows),
        upserted_bill_refs=upserted_bill_refs,
        ensured_member_refs=ensured_member_refs,
        upserted_votes=upserted_votes,
        selected_worker_count=benchmark.selected_worker_count,
        tolerated_distribution_mismatches=tolerated_distribution_mismatches,
        failed_vote_bill_count=len(vote_row_failures),
        vote_row_failures=vote_row_failures,
        age_param_used=vote_bill_list.age_param_used,
    )


def _fetch_vote_bill_list(*, limit_pct: float, page_size: int) -> _VoteBillListResult:
    first = fetch_with_age_attempts(
        VOTE_BILL_ENDPOINT,
        ENDPOINTS_BY_SLUG[VOTE_BILL_ENDPOINT].verify_sample,
        p_index=1,
        p_size=page_size,
        sleep_between=0,
    )
    _ensure_ok(first, "vote bill list fetch failed")
    target_count = _target_count(first.total_count, limit_pct)
    rows = list(first.rows[:target_count])
    age_param = first.age_param_used or {}

    page = 2
    while len(rows) < target_count:
        response = fetch_endpoint_with_retry(
            VOTE_BILL_ENDPOINT,
            age_param,
            p_index=page,
            p_size=page_size,
        )
        _ensure_ok(response, f"vote bill list page {page} fetch failed")
        rows.extend(response.rows[: target_count - len(rows)])
        page += 1

    return _VoteBillListResult(
        total_count=first.total_count,
        target_count=target_count,
        rows=rows,
        age_param_used=first.age_param_used,
    )


def _fetch_vote_rows(bill_id: str) -> list[dict[str, Any]]:
    response = fetch_with_age_attempts(
        VOTE_ROWS_ENDPOINT,
        {"BILL_ID": bill_id},
        p_size=300,
        sleep_between=0,
    )
    _ensure_ok(response, f"vote rows fetch failed for BILL_ID={bill_id}")
    return response.rows


def _fetch_vote_rows_with_retry(
    bill_id: str,
    *,
    retry_delays: tuple[float, ...],
) -> list[dict[str, Any]]:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _fetch_vote_rows(bill_id)
        except Exception as exc:
            if attempts > len(retry_delays):
                raise RuntimeError(f"after {attempts} attempts: {exc}") from exc
            delay = retry_delays[attempts - 1]
            safe_print(
                f"[retry] vote rows bill_id={bill_id} "
                f"attempt={attempts} next_delay={delay:.1f}s error={exc}",
                flush=True,
            )
            time.sleep(delay)


def _fetch_vote_rows_for_bills(
    bill_ids: list[str],
    *,
    worker_count: int,
    retry_delays: tuple[float, ...],
    label: str = "vote rows",
) -> _VoteRowsFetchResult:
    vote_rows_by_bill: dict[str, list[dict[str, Any]]] = {}
    failures: list[VoteRowFailure] = []
    progress = ProgressReporter(label, len(bill_ids))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(_fetch_vote_rows_with_retry, bill_id, retry_delays=retry_delays): bill_id
            for bill_id in bill_ids
        }
        for future in as_completed(futures):
            bill_id = futures[future]
            try:
                vote_rows_by_bill[bill_id] = future.result()
                progress.advance()
            except Exception as exc:  # noqa: BLE001 - source item failures are preserved
                failures.append(
                    VoteRowFailure(
                        bill_id=bill_id,
                        error=str(exc),
                        attempts=len(retry_delays) + 1,
                    )
                )
                progress.advance(errors=1)
    progress.finish()
    return _VoteRowsFetchResult(vote_rows_by_bill, tuple(failures))


def _retry_failed_vote_bills(
    failures: tuple[VoteRowFailure, ...],
    *,
    selected_worker_count: int,
    retry_delays: tuple[float, ...],
) -> _VoteRowsFetchResult:
    failed_ids = [failure.bill_id for failure in failures]
    retry_worker_count = min(5, max(1, selected_worker_count))
    safe_print(
        "[retry] vote rows final pass "
        f"bills={len(failed_ids)} workers={retry_worker_count}",
        flush=True,
    )
    return _fetch_vote_rows_for_bills(
        failed_ids,
        worker_count=retry_worker_count,
        retry_delays=retry_delays,
        label="vote rows final retry",
    )


def _target_count(total_count: int, limit_pct: float) -> int:
    if limit_pct <= 0:
        raise ValueError("limit_pct must be positive")
    if limit_pct <= 1:
        return min(total_count, max(1, math.ceil(total_count * limit_pct)))
    return min(total_count, int(limit_pct))


def _load_canonical_bill_ids(rows: list[dict[str, Any]]) -> dict[str, str]:
    bill_nos = sorted({str(row["BILL_NO"]) for row in rows})
    existing_by_no: dict[str, str] = {}
    if bill_nos:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT bill_no, bill_id FROM bills WHERE bill_no = ANY(%s)",
                (bill_nos,),
            )
            existing_by_no = {str(bill_no): str(bill_id) for bill_no, bill_id in cur.fetchall()}
    return {
        str(row["BILL_ID"]): existing_by_no.get(str(row["BILL_NO"]), str(row["BILL_ID"]))
        for row in rows
    }


def _normalize_bill_ref(row: dict[str, Any], *, bill_id: str | None = None) -> dict[str, Any]:
    return {
        "bill_id": bill_id or _required(row, "BILL_ID"),
        "bill_no": _required(row, "BILL_NO"),
        "bill_name": _required(row, "BILL_NAME"),
        "committee": _blank_to_none(row.get("CURR_COMMITTEE")),
        "committee_id": _blank_to_none(row.get("CURR_COMMITTEE_ID")),
        "proc_result": _blank_to_none(row.get("PROC_RESULT_CD")),
        "proc_dt": _blank_to_none(row.get("PROC_DT")),
        "detail_link": _blank_to_none(row.get("LINK_URL")),
        "age": int(row.get("AGE") or 22),
    }


def _normalize_member_refs(
    vote_rows_by_bill: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    names_by_code: dict[str, str] = {}
    for rows in vote_rows_by_bill.values():
        for row in rows:
            mona_cd = _blank_to_none(row.get("MONA_CD"))
            hg_nm = _blank_to_none(row.get("HG_NM"))
            if mona_cd:
                names_by_code[str(mona_cd)] = str(hg_nm or mona_cd)
    return [
        {"mona_cd": mona_cd, "hg_nm": hg_nm}
        for mona_cd, hg_nm in sorted(names_by_code.items())
    ]


def _normalize_vote_row(row: dict[str, Any], *, bill_id: str | None = None) -> dict[str, Any]:
    return {
        "bill_id": bill_id or _required(row, "BILL_ID"),
        "mona_cd": _required(row, "MONA_CD"),
        "vote_date": _parse_vote_date(_required(row, "VOTE_DATE")),
        "result_vote_mod": _required(row, "RESULT_VOTE_MOD"),
        "poly_nm_at_vote": _required(row, "POLY_NM"),
        "session_cd": _int_or_none(row.get("SESSION_CD")),
        "currents_cd": _int_or_none(row.get("CURRENTS_CD")),
    }


def _validate_vote_distribution(vote_bill: dict[str, Any], vote_rows: list[dict[str, Any]]) -> bool:
    counts = Counter(str(row.get("RESULT_VOTE_MOD") or "") for row in vote_rows)
    expected = {
        "찬성": _int_or_zero(vote_bill.get("YES_TCNT")),
        "반대": _int_or_zero(vote_bill.get("NO_TCNT")),
        "기권": _int_or_zero(vote_bill.get("BLANK_TCNT")),
    }
    expected_vote_count = _int_or_zero(vote_bill.get("VOTE_TCNT"))
    missing_member_rows = max(_int_or_zero(vote_bill.get("MEMBER_TCNT")) - len(vote_rows), 0)
    if sum(expected.values()) != expected_vote_count:
        raise RuntimeError(f"vote aggregate mismatch for {vote_bill.get('BILL_ID')}")

    mismatch_delta = sum(
        abs(counts[result_vote_mod] - expected_count)
        for result_vote_mod, expected_count in expected.items()
    )
    actual_vote_count = sum(counts[result_vote_mod] for result_vote_mod in expected)
    if mismatch_delta == 0:
        return True
    if (
        abs(actual_vote_count - expected_vote_count) <= missing_member_rows
        and mismatch_delta <= max(2, missing_member_rows * 2)
    ):
        return False

    bill_id = vote_bill.get("BILL_ID")
    actual = {result_vote_mod: counts[result_vote_mod] for result_vote_mod in expected}
    raise RuntimeError(
        f"vote distribution mismatch for {bill_id}: "
        f"expected={expected} actual={actual}"
    )


def _parse_vote_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d %H%M%S").replace(tzinfo=SEOUL)


def _required(row: dict[str, Any], key: str) -> Any:
    value = _blank_to_none(row.get(key))
    if value is None:
        raise ValueError(f"vote API row missing {key}")
    return value


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _int_or_zero(value: Any) -> int:
    return int(value or 0)


def _ensure_ok(response: ApiResponse, message: str) -> None:
    if response.status != "ok":
        detail = response.error or response.status
        raise RuntimeError(f"{message}: {detail}")


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value
