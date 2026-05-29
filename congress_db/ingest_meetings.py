"""meetings + meeting_bills 적재."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .agenda_parser import parse_agenda_item
from .api_client import ApiResponse, fetch_endpoint, fetch_with_age_attempts
from .benchmark import (
    DEFAULT_WORKER_LEVELS,
    BenchmarkResult,
    measure_workers,
    render_parallel_benchmark,
)
from .db import execute_many, get_conn
from .meeting_id import extract_mnts_id
from .minutes_web_list import collect_minutes_web_list, web_meeting_to_row
from .progress import ProgressReporter

PLENARY_ENDPOINT = "nzbyfwhwaoanttzje"
COMMITTEE_ENDPOINT = "ncwgseseafwbuheph"
AUDIT_ENDPOINT = "VCONFAPIGCONFLIST"
INVESTIGATION_ENDPOINT = "VCONFPIPCONFLIST"
CONFIRMATION_ENDPOINT = "VCONFCFRMCONFLIST"
VCONFBILL_ENDPOINT = "VCONFBILLCONFLIST"
SEOUL = ZoneInfo("Asia/Seoul")
DEFAULT_MEETINGS_BENCHMARK_OUTPUT = Path("docs/MEETINGS-PARALLEL-BENCHMARK.md")
DEFAULT_VCONFBILL_RETRY_DELAYS = (1.0, 4.0, 16.0)


@dataclass(frozen=True)
class IngestMeetingsResult:
    """회의 메타 적재 결과."""

    total_count: int
    target_count: int
    meeting_count: int
    agenda_candidate_count: int
    meeting_bill_count: int
    selected_worker_count: int
    new_meeting_ids: tuple[int, ...]
    changed_meeting_ids: tuple[int, ...]
    stale_meeting_ids: tuple[int, ...]
    html_unavailable_mnts_ids: tuple[int, ...]
    web_only_mnts_ids: tuple[int, ...]
    openapi_only_mnts_ids: tuple[int, ...]
    age_params_by_source: dict[str, dict[str, str] | None]


@dataclass(frozen=True)
class _SourceRequest:
    endpoint: str
    params: dict[str, str]


@dataclass(frozen=True)
class _FetchedRequest:
    request: _SourceRequest
    total_count: int
    rows: list[dict[str, Any]]
    age_param_used: dict[str, str] | None


@dataclass
class _FetchState:
    request: _SourceRequest
    total_count: int
    rows: list[dict[str, Any]]
    age_param_used: dict[str, str] | None
    next_page: int = 2


_UPSERT_MEETINGS_SQL = """
    INSERT INTO meetings (
        mnts_id, title, meeting_type, session_no, degree, conf_date,
        comm_name, is_temporary, is_appendix
    )
    VALUES (
        %(mnts_id)s, %(title)s, %(meeting_type)s, %(session_no)s, %(degree)s,
        %(conf_date)s, %(comm_name)s, %(is_temporary)s, %(is_appendix)s
    )
    ON CONFLICT (mnts_id) DO UPDATE SET
        title         = EXCLUDED.title,
        meeting_type  = EXCLUDED.meeting_type,
        session_no    = COALESCE(EXCLUDED.session_no, meetings.session_no),
        degree        = COALESCE(EXCLUDED.degree, meetings.degree),
        conf_date     = EXCLUDED.conf_date,
        comm_name     = COALESCE(EXCLUDED.comm_name, meetings.comm_name),
        is_temporary  = EXCLUDED.is_temporary,
        is_appendix   = EXCLUDED.is_appendix,
        fetched_at    = now()
"""

_INSERT_MEETING_BILLS_SQL = """
    INSERT INTO meeting_bills (meeting_id, bill_id, source)
    VALUES (%(meeting_id)s, %(bill_id)s, %(source)s)
    ON CONFLICT (meeting_id, bill_id) DO UPDATE SET
        source = CASE
            WHEN meeting_bills.source = EXCLUDED.source THEN EXCLUDED.source
            WHEN meeting_bills.source = 'both' OR EXCLUDED.source = 'both' THEN 'both'
            ELSE 'both'
        END
"""


def ingest_meetings(
    *,
    calibration_limit: int | None = 500,
    page_size: int = 1000,
    years: Sequence[int] | None = None,
    benchmark_sample_size: int = 100,
    worker_levels: tuple[int, ...] = DEFAULT_WORKER_LEVELS,
    benchmark_output_path: Path = DEFAULT_MEETINGS_BENCHMARK_OUTPUT,
) -> IngestMeetingsResult:
    """22대 회의 메타를 캘리브레이션 분량만큼 적재한다."""
    print(
        f"[ingest-meetings] calibration target unique meetings={calibration_limit or 'all'}",
        flush=True,
    )
    web_list = collect_minutes_web_list()
    web_meetings = web_list.meetings
    fetched = _fetch_meeting_sources(
        years=years or _default_years(),
        calibration_limit=calibration_limit,
        page_size=page_size,
        unique_target_count=len(web_meetings),
    )
    api_meeting_rows, agenda_drafts = _normalize_meeting_sources(fetched)
    meeting_rows = {
        meeting.mnts_id: _enrich_web_meeting_row(web_meeting_to_row(meeting), api_meeting_rows.get(meeting.mnts_id))
        for meeting in web_meetings
    }
    web_meeting_ids = set(meeting_rows)
    agenda_drafts = [row for row in agenda_drafts if row["meeting_id"] in web_meeting_ids]
    meeting_bill_scope_ids = (
        web_meeting_ids
        if calibration_limit is None
        else {row["meeting_id"] for row in agenda_drafts}
    )
    agenda_rows = _attach_agenda_bill_ids(agenda_drafts)
    agenda_pairs = _meeting_bill_pairs_from_agenda(agenda_rows)
    vconf_pairs, benchmark = _fetch_vconfbill_pairs(
        sorted({row["bill_id"] for row in agenda_rows if row.get("bill_id")}),
        known_meeting_ids=web_meeting_ids,
        sample_size=benchmark_sample_size,
        worker_levels=worker_levels,
        output_path=benchmark_output_path,
    )
    meeting_bill_rows = _merge_meeting_bill_pairs(agenda_pairs, vconf_pairs)
    new_meeting_ids, changed_meeting_ids = _reconcile_meeting_rows(meeting_rows)
    api_meeting_ids = set(api_meeting_rows)
    coverage_ids_available = calibration_limit is None

    with get_conn() as conn:
        stale_meeting_ids = (
            _prune_stale_meetings(conn, web_meeting_ids)
            if calibration_limit is None
            else ()
        )
        upserted_meetings = execute_many(conn, _UPSERT_MEETINGS_SQL, meeting_rows.values())
        _replace_meeting_bills_for_meetings(conn, list(meeting_bill_scope_ids))
        inserted_meeting_bills = execute_many(conn, _INSERT_MEETING_BILLS_SQL, meeting_bill_rows)
        conn.commit()

    return IngestMeetingsResult(
        total_count=len(web_meetings),
        target_count=len(web_meetings),
        meeting_count=upserted_meetings,
        agenda_candidate_count=len(agenda_rows),
        meeting_bill_count=inserted_meeting_bills,
        selected_worker_count=benchmark.selected_worker_count if benchmark else 0,
        new_meeting_ids=new_meeting_ids,
        changed_meeting_ids=changed_meeting_ids,
        stale_meeting_ids=stale_meeting_ids,
        html_unavailable_mnts_ids=tuple(item.mnts_id for item in web_list.html_unavailable),
        web_only_mnts_ids=tuple(sorted(web_meeting_ids - api_meeting_ids)) if coverage_ids_available else (),
        openapi_only_mnts_ids=tuple(sorted(api_meeting_ids - web_meeting_ids)) if coverage_ids_available else (),
        age_params_by_source={
            item.request.endpoint: item.age_param_used
            for item in fetched
            if item.age_param_used is not None
        },
    )


def _fetch_meeting_sources(
    *,
    years: Sequence[int],
    calibration_limit: int | None,
    page_size: int,
    unique_target_count: int,
) -> list[_FetchedRequest]:
    first_pages: list[_FetchedRequest] = []
    for request in _source_requests(years):
        response = fetch_with_age_attempts(
            request.endpoint,
            request.params,
            p_index=1,
            p_size=page_size,
            sleep_between=0,
        )
        if response.status == "no_data":
            first_pages.append(_FetchedRequest(request, 0, [], response.age_param_used))
            continue
        _ensure_ok(response, f"meeting API fetch failed for {request.endpoint}")
        first_pages.append(
            _FetchedRequest(request, response.total_count, list(response.rows), response.age_param_used)
        )

    states = [
        _FetchState(
            request=first.request,
            total_count=first.total_count,
            rows=list(first.rows),
            age_param_used=first.age_param_used,
        )
        for first in first_pages
    ]
    seen_meeting_ids = _meeting_ids_from_states(states)
    _fetch_until_target_meetings(
        states,
        seen_meeting_ids=seen_meeting_ids,
        calibration_limit=calibration_limit,
        page_size=page_size,
        unique_target_count=unique_target_count,
    )
    return [
        _FetchedRequest(
            request=state.request,
            total_count=state.total_count,
            rows=state.rows,
            age_param_used=state.age_param_used,
        )
        for state in states
    ]


def _source_requests(years: Sequence[int]) -> list[_SourceRequest]:
    requests: list[_SourceRequest] = []
    for year in years:
        requests.append(_SourceRequest(PLENARY_ENDPOINT, {"CONF_DATE": str(year)}))
        requests.append(_SourceRequest(COMMITTEE_ENDPOINT, {"CONF_DATE": str(year)}))
    requests.extend(
        [
            _SourceRequest(AUDIT_ENDPOINT, {}),
            _SourceRequest(INVESTIGATION_ENDPOINT, {}),
            _SourceRequest(CONFIRMATION_ENDPOINT, {}),
        ]
    )
    return requests


def _fetch_until_target_meetings(
    states: list[_FetchState],
    *,
    seen_meeting_ids: set[int],
    calibration_limit: int | None,
    page_size: int,
    unique_target_count: int,
) -> None:
    if calibration_limit is not None and calibration_limit <= 0:
        raise ValueError("calibration_limit must be positive")

    progress = ProgressReporter(
        "meeting metadata unique mnts_id",
        calibration_limit or unique_target_count,
    )
    row_progress = ProgressReporter(
        "meeting metadata rows",
        sum(state.total_count for state in states),
        min_interval=5.0,
    )
    progress.start()
    progress.set(len(seen_meeting_ids))
    row_progress.start()
    row_progress.set(sum(len(state.rows) for state in states))
    while calibration_limit is None or len(seen_meeting_ids) < calibration_limit:
        candidates = [state for state in states if len(state.rows) < state.total_count]
        if not candidates:
            row_progress.finish()
            progress.finish()
            return
        progressed = False
        for state in sorted(candidates, key=lambda item: item.total_count - len(item.rows), reverse=True):
            if calibration_limit is not None and len(seen_meeting_ids) >= calibration_limit:
                break
            rows = _fetch_next_meeting_page(state, page_size=page_size)
            if not rows:
                continue
            progressed = True
            state.rows.extend(rows)
            for row in rows:
                seen_meeting_ids.add(_meeting_id_from_row(state.request.endpoint, row))
            row_progress.set(sum(len(item.rows) for item in states))
            progress.set(len(seen_meeting_ids))
        if not progressed:
            row_progress.finish()
            progress.finish()
            return
    progress.finish()


def _fetch_next_meeting_page(state: _FetchState, *, page_size: int) -> list[dict[str, Any]]:
    response = fetch_endpoint(
        state.request.endpoint,
        {**state.request.params, **(state.age_param_used or {})},
        p_index=state.next_page,
        p_size=page_size,
    )
    _ensure_ok(response, f"meeting API page {state.next_page} failed for {state.request.endpoint}")
    state.next_page += 1
    return list(response.rows)


def _meeting_ids_from_states(states: list[_FetchState]) -> set[int]:
    return {
        _meeting_id_from_row(state.request.endpoint, row)
        for state in states
        for row in state.rows
    }


def _meeting_id_from_row(endpoint: str, row: dict[str, Any]) -> int:
    if endpoint in {PLENARY_ENDPOINT, COMMITTEE_ENDPOINT}:
        return extract_mnts_id(row.get("CONFER_NUM") or row.get("PDF_LINK_URL"))
    return extract_mnts_id(row.get("DOWN_URL"))


def _normalize_meeting_sources(
    fetched: list[_FetchedRequest],
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    meetings: dict[int, dict[str, Any]] = {}
    agenda_candidates: list[dict[str, Any]] = []
    for item in fetched:
        for row in item.rows:
            meeting = _normalize_meeting_row(item.request.endpoint, row)
            _merge_meeting(meetings, meeting)
            agenda = _normalize_agenda_row(meeting["mnts_id"], row)
            if agenda:
                agenda_candidates.append(agenda)
    return meetings, _dedupe_agenda_candidates(agenda_candidates)


def _normalize_meeting_row(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    if endpoint in {PLENARY_ENDPOINT, COMMITTEE_ENDPOINT}:
        return _normalize_standard_meeting(endpoint, row)
    return _normalize_special_meeting(endpoint, row)


def _normalize_standard_meeting(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    title = _required(row, "TITLE")
    comm_name = _blank_to_none(row.get("COMM_NAME"))
    return {
        "mnts_id": extract_mnts_id(row.get("CONFER_NUM") or row.get("PDF_LINK_URL")),
        "title": title,
        "meeting_type": _standard_meeting_type(endpoint, row),
        "session_no": _parse_session_no(title),
        "degree": _parse_degree(title),
        "conf_date": _parse_date(row.get("CONF_DATE"), title),
        "comm_name": comm_name,
        "is_temporary": _is_temporary_title(title),
        "is_appendix": _is_appendix_title(title),
    }


def _normalize_special_meeting(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    class_name = _blank_to_none(row.get("CONF_KND"))
    comm_name = _blank_to_none(row.get("CMIT_NM"))
    session_no = _parse_session_no(row.get("SESS"))
    degree = _blank_to_none(row.get("DGR"))
    conf_date = _parse_date(row.get("CONF_DT"), None)
    return {
        "mnts_id": extract_mnts_id(row.get("DOWN_URL")),
        "title": _special_title(comm_name, class_name, row.get("SESS"), degree, conf_date),
        "meeting_type": _special_meeting_type(endpoint),
        "session_no": session_no,
        "degree": degree,
        "conf_date": conf_date,
        "comm_name": comm_name,
        "is_temporary": False,
        "is_appendix": False,
    }


def _standard_meeting_type(endpoint: str, row: dict[str, Any]) -> str:
    if endpoint == PLENARY_ENDPOINT:
        return "본회의"
    title = str(row.get("TITLE") or "")
    class_name = str(row.get("CLASS_NAME") or "")
    comm_name = str(row.get("COMM_NAME") or "")
    if "소위원회" in title or "소위원회" in comm_name:
        return "소위원회"
    if "특별" in title or "특별" in class_name or "특별" in comm_name:
        return "특별위"
    return "상임위"


def _special_meeting_type(endpoint: str) -> str:
    return {
        AUDIT_ENDPOINT: "국정감사",
        INVESTIGATION_ENDPOINT: "국정조사",
        CONFIRMATION_ENDPOINT: "인사청문회",
    }[endpoint]


def _special_title(
    comm_name: str | None,
    class_name: str | None,
    sess: Any,
    degree: str | None,
    conf_date: date,
) -> str:
    parts = [comm_name, class_name, _blank_to_none(sess), degree, f"({conf_date.isoformat()})"]
    return " ".join(str(part) for part in parts if part)


def _merge_meeting(meetings: dict[int, dict[str, Any]], meeting: dict[str, Any]) -> None:
    existing = meetings.get(meeting["mnts_id"])
    if existing is None:
        meetings[meeting["mnts_id"]] = meeting
        return
    _validate_duplicate_meeting(existing, meeting)
    for key in ("session_no", "degree", "comm_name"):
        if not existing.get(key) and meeting.get(key):
            existing[key] = meeting[key]
    existing["is_temporary"] = bool(existing.get("is_temporary") or meeting.get("is_temporary"))
    existing["is_appendix"] = bool(existing.get("is_appendix") or meeting.get("is_appendix"))


def _enrich_web_meeting_row(
    web_row: dict[str, Any],
    api_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if api_row is None:
        return web_row
    for key in ("session_no", "degree", "comm_name"):
        if not web_row.get(key) and api_row.get(key):
            web_row[key] = api_row[key]
    return web_row


def _reconcile_meeting_rows(
    meeting_rows: dict[int, dict[str, Any]],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if not meeting_rows:
        return (), ()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id, title, meeting_type, session_no, degree, conf_date,
                   comm_name, is_temporary, is_appendix
            FROM meetings
            WHERE mnts_id = ANY(%s)
            """,
            (list(meeting_rows),),
        )
        existing = {
            row[0]: {
                "title": row[1],
                "meeting_type": row[2],
                "session_no": row[3],
                "degree": row[4],
                "conf_date": row[5],
                "comm_name": row[6],
                "is_temporary": row[7],
                "is_appendix": row[8],
            }
            for row in cur.fetchall()
        }

    new_ids: list[int] = []
    changed_ids: list[int] = []
    for mnts_id, row in meeting_rows.items():
        old = existing.get(mnts_id)
        if old is None:
            new_ids.append(mnts_id)
        elif _meeting_row_changed(old, row):
            changed_ids.append(mnts_id)
    return tuple(sorted(new_ids)), tuple(sorted(changed_ids))


def _meeting_row_changed(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    return any(
        existing.get(key) != incoming.get(key)
        for key in (
            "title",
            "meeting_type",
            "session_no",
            "degree",
            "conf_date",
            "comm_name",
            "is_temporary",
            "is_appendix",
        )
    )


def _validate_duplicate_meeting(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    if existing["conf_date"] != incoming["conf_date"]:
        raise RuntimeError(
            f"meeting duplicate date mismatch for {existing['mnts_id']}: "
            f"{existing['conf_date']} != {incoming['conf_date']}"
        )


def _normalize_agenda_row(meeting_id: int, row: dict[str, Any]) -> dict[str, Any] | None:
    sub_name = _blank_to_none(row.get("SUB_NAME"))
    if not sub_name:
        return None
    item = parse_agenda_item(str(sub_name))
    return {
        "meeting_id": meeting_id,
        "order_no": item.order_no,
        "sub_name": item.sub_name,
        "bill_no": item.bill_no,
    }


def _dedupe_agenda_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[int, int | None, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (row["meeting_id"], row["order_no"], row["sub_name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _attach_agenda_bill_ids(agenda_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bill_nos = sorted({row["bill_no"] for row in agenda_rows if row.get("bill_no")})
    bill_ids_by_no = _load_bill_ids_by_no(bill_nos)
    result: list[dict[str, Any]] = []
    for row in agenda_rows:
        result.append(
            {
                "meeting_id": row["meeting_id"],
                "order_no": row["order_no"],
                "sub_name": row["sub_name"],
                "bill_id": bill_ids_by_no.get(row.get("bill_no")),
            }
        )
    return result


def _load_bill_ids_by_no(bill_nos: list[str]) -> dict[str, str]:
    if not bill_nos:
        return {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT bill_no, bill_id FROM bills WHERE bill_no = ANY(%s)", (bill_nos,))
        return {bill_no: bill_id for bill_no, bill_id in cur.fetchall()}


def _meeting_bill_pairs_from_agenda(rows: list[dict[str, Any]]) -> set[tuple[int, str]]:
    return {
        (row["meeting_id"], row["bill_id"])
        for row in rows
        if row.get("bill_id")
    }


def _fetch_vconfbill_pairs(
    bill_ids: list[str],
    *,
    known_meeting_ids: set[int],
    sample_size: int,
    worker_levels: tuple[int, ...],
    output_path: Path,
) -> tuple[set[tuple[int, str]], BenchmarkResult | None]:
    if not bill_ids:
        return set(), None
    benchmark = measure_workers(
        lambda bill_id, worker_count: _fetch_vconfbill_rows(str(bill_id)),
        items=bill_ids[:sample_size],
        levels=worker_levels,
    )
    render_parallel_benchmark(benchmark, output_path)
    rows_by_bill = _fetch_vconfbill_rows_for_bills(
        bill_ids,
        worker_count=benchmark.selected_worker_count,
    )
    pairs: set[tuple[int, str]] = set()
    for bill_id, rows in rows_by_bill.items():
        for row in rows:
            meeting_id = extract_mnts_id(row.get("DOWN_URL"))
            if meeting_id in known_meeting_ids:
                pairs.add((meeting_id, bill_id))
    return pairs, benchmark


def _fetch_vconfbill_rows_for_bills(
    bill_ids: list[str],
    *,
    worker_count: int,
    retry_delays: tuple[float, ...] = DEFAULT_VCONFBILL_RETRY_DELAYS,
) -> dict[str, list[dict[str, Any]]]:
    rows_by_bill, errors = _fetch_vconfbill_rows_batch(
        bill_ids,
        worker_count=worker_count,
        retry_delays=retry_delays,
        label="VCONFBILLCONFLIST",
    )
    if errors:
        retry_worker_count = min(5, max(1, worker_count))
        print(
            "[retry] VCONFBILLCONFLIST final pass "
            f"bills={len(errors)} workers={retry_worker_count}",
            flush=True,
        )
        retried_rows, errors = _fetch_vconfbill_rows_batch(
            sorted(errors),
            worker_count=retry_worker_count,
            retry_delays=retry_delays,
            label="VCONFBILLCONFLIST final retry",
        )
        rows_by_bill.update(retried_rows)

    if errors:
        sample = "; ".join(f"{bill_id}: {error}" for bill_id, error in list(errors.items())[:5])
        raise RuntimeError(
            "VCONFBILLCONFLIST finished with persistent failures: "
            f"errors={len(errors)} sample={sample}"
        )
    return rows_by_bill


def _fetch_vconfbill_rows_batch(
    bill_ids: list[str],
    *,
    worker_count: int,
    retry_delays: tuple[float, ...],
    label: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    rows_by_bill: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    progress = ProgressReporter(label, len(bill_ids))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(_fetch_vconfbill_rows_with_retry, bill_id, retry_delays=retry_delays): bill_id
            for bill_id in bill_ids
        }
        for future in as_completed(futures):
            bill_id = futures[future]
            try:
                rows_by_bill[bill_id] = future.result()
                progress.advance()
            except Exception as exc:  # noqa: BLE001 - boundary failures are retried above
                errors[bill_id] = str(exc)
                progress.advance(errors=1)
    progress.finish()
    return rows_by_bill, errors


def _fetch_vconfbill_rows_with_retry(
    bill_id: str,
    *,
    retry_delays: tuple[float, ...],
) -> list[dict[str, Any]]:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _fetch_vconfbill_rows(bill_id)
        except Exception as exc:
            if attempts > len(retry_delays):
                raise RuntimeError(f"after {attempts} attempts: {exc}") from exc
            delay = retry_delays[attempts - 1]
            print(
                f"[retry] VCONFBILLCONFLIST bill_id={bill_id} "
                f"attempt={attempts} next_delay={delay:.1f}s error={exc}",
                flush=True,
            )
            if delay:
                time.sleep(delay)


def _fetch_vconfbill_rows(bill_id: str) -> list[dict[str, Any]]:
    first = fetch_with_age_attempts(
        VCONFBILL_ENDPOINT,
        {"BILL_ID": bill_id},
        p_size=100,
        sleep_between=0,
    )
    if first.status == "no_data":
        return []
    _ensure_ok(first, f"VCONFBILLCONFLIST fetch failed for BILL_ID={bill_id}")
    rows = list(first.rows)
    page = 2
    while len(rows) < first.total_count:
        response = fetch_endpoint(
            VCONFBILL_ENDPOINT,
            {"BILL_ID": bill_id, **(first.age_param_used or {})},
            p_index=page,
            p_size=100,
        )
        _ensure_ok(response, f"VCONFBILLCONFLIST page {page} failed for BILL_ID={bill_id}")
        if not response.rows:
            break
        rows.extend(response.rows)
        page += 1
    return rows


def _merge_meeting_bill_pairs(
    agenda_pairs: set[tuple[int, str]],
    vconf_pairs: set[tuple[int, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meeting_id, bill_id in sorted(agenda_pairs | vconf_pairs):
        if (meeting_id, bill_id) in agenda_pairs and (meeting_id, bill_id) in vconf_pairs:
            source = "both"
        elif (meeting_id, bill_id) in vconf_pairs:
            source = "vconfbill"
        else:
            source = "agenda"
        rows.append({"meeting_id": meeting_id, "bill_id": bill_id, "source": source})
    return rows


def _replace_meeting_bills_for_meetings(conn: Any, meeting_ids: list[int]) -> None:
    if not meeting_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = ANY(%s)", (meeting_ids,))


def _prune_stale_meetings(conn: Any, canonical_meeting_ids: set[int]) -> tuple[int, ...]:
    if not canonical_meeting_ids:
        raise RuntimeError("refusing to prune stale meetings without canonical web meeting ids")

    canonical_ids = sorted(canonical_meeting_ids)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM meetings")
        existing_count = cur.fetchone()[0]
        if existing_count >= 100 and len(canonical_ids) < existing_count * 0.8:
            raise RuntimeError(
                "refusing to prune stale meetings because the canonical web list is "
                f"unexpectedly small: existing={existing_count} canonical={len(canonical_ids)}"
            )

        cur.execute(
            """
            SELECT mnts_id
            FROM meetings
            WHERE NOT (mnts_id = ANY(%s))
            ORDER BY mnts_id
            """,
            (canonical_ids,),
        )
        stale_ids = tuple(row[0] for row in cur.fetchall())
        if not stale_ids:
            return ()

        stale_id_list = list(stale_ids)
        stale_item_keys = [str(mnts_id) for mnts_id in stale_ids]
        cur.execute("DELETE FROM utterances WHERE meeting_id = ANY(%s)", (stale_id_list,))
        cur.execute("DELETE FROM session_groups WHERE meeting_id = ANY(%s)", (stale_id_list,))
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = ANY(%s)", (stale_id_list,))
        cur.execute(
            """
            DELETE FROM dead_letters
            WHERE source = 'minutes.html'
              AND item_key = ANY(%s)
            """,
            (stale_item_keys,),
        )
        cur.execute("DELETE FROM meetings WHERE mnts_id = ANY(%s)", (stale_id_list,))
        return stale_ids


def _default_years() -> tuple[int, ...]:
    return tuple(range(2024, datetime.now(SEOUL).year + 1))


def _parse_date(value: Any, fallback_text: str | None) -> date:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    if fallback_text:
        match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", fallback_text)
        if match:
            year, month, day = (int(part) for part in match.groups())
            return date(year, month, day)
    raise ValueError(f"cannot parse meeting date from {value!r}")


def _parse_session_no(value: Any) -> int | None:
    match = re.search(r"제\s*(\d+)\s*회", str(value or ""))
    return int(match.group(1)) if match else None


def _parse_degree(value: Any) -> str | None:
    match = re.search(r"제\s*\d+\s*차|개회식", str(value or ""))
    return match.group(0).replace(" ", "") if match else None


def _is_temporary_title(value: str) -> bool:
    return "[임시]" in value


def _is_appendix_title(value: str) -> bool:
    return "(부록)" in value


def _required(row: dict[str, Any], key: str) -> Any:
    value = _blank_to_none(row.get(key))
    if value is None:
        raise ValueError(f"meeting API row missing {key}")
    return value


def _ensure_ok(response: ApiResponse, message: str) -> None:
    if response.status != "ok":
        detail = response.error or response.status
        raise RuntimeError(f"{message}: {detail}")


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value
