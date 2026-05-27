"""meetings + agenda_items + meeting_bills 적재."""

from __future__ import annotations

import re
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

PLENARY_ENDPOINT = "nzbyfwhwaoanttzje"
COMMITTEE_ENDPOINT = "ncwgseseafwbuheph"
AUDIT_ENDPOINT = "VCONFAPIGCONFLIST"
INVESTIGATION_ENDPOINT = "VCONFPIPCONFLIST"
CONFIRMATION_ENDPOINT = "VCONFCFRMCONFLIST"
VCONFBILL_ENDPOINT = "VCONFBILLCONFLIST"
SEOUL = ZoneInfo("Asia/Seoul")
DEFAULT_MEETINGS_BENCHMARK_OUTPUT = Path("docs/MEETINGS-PARALLEL-BENCHMARK.md")


@dataclass(frozen=True)
class IngestMeetingsResult:
    """회의 메타 적재 결과."""

    total_count: int
    target_count: int
    meeting_count: int
    agenda_item_count: int
    meeting_bill_count: int
    selected_worker_count: int
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
        mnts_id, conf_id, title, meeting_type, class_name, dae_num,
        session_no, degree, conf_date, comm_name, comm_code,
        pdf_link_url, vod_link_url, conf_link_url, source_api
    )
    VALUES (
        %(mnts_id)s, %(conf_id)s, %(title)s, %(meeting_type)s, %(class_name)s, %(dae_num)s,
        %(session_no)s, %(degree)s, %(conf_date)s, %(comm_name)s, %(comm_code)s,
        %(pdf_link_url)s, %(vod_link_url)s, %(conf_link_url)s, %(source_api)s
    )
    ON CONFLICT (mnts_id) DO UPDATE SET
        conf_id       = COALESCE(EXCLUDED.conf_id, meetings.conf_id),
        title         = EXCLUDED.title,
        meeting_type  = EXCLUDED.meeting_type,
        class_name    = COALESCE(EXCLUDED.class_name, meetings.class_name),
        dae_num       = EXCLUDED.dae_num,
        session_no    = COALESCE(EXCLUDED.session_no, meetings.session_no),
        degree        = COALESCE(EXCLUDED.degree, meetings.degree),
        conf_date     = EXCLUDED.conf_date,
        comm_name     = COALESCE(EXCLUDED.comm_name, meetings.comm_name),
        comm_code     = COALESCE(EXCLUDED.comm_code, meetings.comm_code),
        pdf_link_url  = COALESCE(EXCLUDED.pdf_link_url, meetings.pdf_link_url),
        vod_link_url  = COALESCE(EXCLUDED.vod_link_url, meetings.vod_link_url),
        conf_link_url = COALESCE(EXCLUDED.conf_link_url, meetings.conf_link_url),
        source_api    = CASE
            WHEN meetings.source_api = EXCLUDED.source_api THEN EXCLUDED.source_api
            WHEN meetings.source_api = 'multi' OR EXCLUDED.source_api = 'multi' THEN 'multi'
            ELSE 'multi'
        END,
        fetched_at    = now()
"""

_INSERT_AGENDA_SQL = """
    INSERT INTO agenda_items (meeting_id, order_no, sub_name, bill_id)
    VALUES (%(meeting_id)s, %(order_no)s, %(sub_name)s, %(bill_id)s)
    ON CONFLICT (meeting_id, order_no, sub_name) DO UPDATE SET
        bill_id = EXCLUDED.bill_id
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
    page_size: int = 100,
    years: Sequence[int] | None = None,
    benchmark_sample_size: int = 100,
    worker_levels: tuple[int, ...] = DEFAULT_WORKER_LEVELS,
    benchmark_output_path: Path = DEFAULT_MEETINGS_BENCHMARK_OUTPUT,
) -> IngestMeetingsResult:
    """22대 회의 메타를 캘리브레이션 분량만큼 적재한다."""
    fetched = _fetch_meeting_sources(
        years=years or _default_years(),
        calibration_limit=calibration_limit,
        page_size=page_size,
    )
    meeting_rows, agenda_drafts = _normalize_meeting_sources(fetched)
    agenda_rows = _attach_agenda_bill_ids(agenda_drafts)
    agenda_pairs = _meeting_bill_pairs_from_agenda(agenda_rows)
    vconf_pairs, benchmark = _fetch_vconfbill_pairs(
        sorted({row["bill_id"] for row in agenda_rows if row.get("bill_id")}),
        known_meeting_ids=set(meeting_rows),
        sample_size=benchmark_sample_size,
        worker_levels=worker_levels,
        output_path=benchmark_output_path,
    )
    meeting_bill_rows = _merge_meeting_bill_pairs(agenda_pairs, vconf_pairs)

    with get_conn() as conn:
        upserted_meetings = execute_many(conn, _UPSERT_MEETINGS_SQL, meeting_rows.values())
        _replace_children_for_meetings(conn, list(meeting_rows))
        inserted_agenda = execute_many(conn, _INSERT_AGENDA_SQL, agenda_rows)
        inserted_meeting_bills = execute_many(conn, _INSERT_MEETING_BILLS_SQL, meeting_bill_rows)
        conn.commit()

    return IngestMeetingsResult(
        total_count=sum(item.total_count for item in fetched),
        target_count=calibration_limit or sum(item.total_count for item in fetched),
        meeting_count=upserted_meetings,
        agenda_item_count=inserted_agenda,
        meeting_bill_count=inserted_meeting_bills,
        selected_worker_count=benchmark.selected_worker_count if benchmark else 0,
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
) -> None:
    if calibration_limit is not None and calibration_limit <= 0:
        raise ValueError("calibration_limit must be positive")

    while calibration_limit is None or len(seen_meeting_ids) < calibration_limit:
        candidates = [state for state in states if len(state.rows) < state.total_count]
        if not candidates:
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
        if not progressed:
            return


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
    agenda_items: list[dict[str, Any]] = []
    for item in fetched:
        for row in item.rows:
            meeting = _normalize_meeting_row(item.request.endpoint, row)
            _merge_meeting(meetings, meeting)
            agenda = _normalize_agenda_row(meeting["mnts_id"], row)
            if agenda:
                agenda_items.append(agenda)
    return meetings, _dedupe_agenda_items(agenda_items)


def _normalize_meeting_row(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    if endpoint in {PLENARY_ENDPOINT, COMMITTEE_ENDPOINT}:
        return _normalize_standard_meeting(endpoint, row)
    return _normalize_special_meeting(endpoint, row)


def _normalize_standard_meeting(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    title = _required(row, "TITLE")
    comm_name = _blank_to_none(row.get("COMM_NAME"))
    return {
        "mnts_id": extract_mnts_id(row.get("CONFER_NUM") or row.get("PDF_LINK_URL")),
        "conf_id": _blank_to_none(row.get("CONF_ID")),
        "title": title,
        "meeting_type": _standard_meeting_type(endpoint, row),
        "class_name": _blank_to_none(row.get("CLASS_NAME")),
        "dae_num": int(row.get("DAE_NUM") or 22),
        "session_no": _parse_session_no(title),
        "degree": _parse_degree(title),
        "conf_date": _parse_date(row.get("CONF_DATE"), title),
        "comm_name": comm_name,
        "comm_code": _blank_to_none(row.get("DEPT_CD")),
        "pdf_link_url": _blank_to_none(row.get("PDF_LINK_URL") or row.get("PDF_FILE_ID")),
        "vod_link_url": _blank_to_none(row.get("VOD_LINK_URL")),
        "conf_link_url": _blank_to_none(row.get("CONF_LINK_URL")),
        "source_api": endpoint,
    }


def _normalize_special_meeting(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    class_name = _blank_to_none(row.get("CONF_KND"))
    comm_name = _blank_to_none(row.get("CMIT_NM"))
    session_no = _parse_session_no(row.get("SESS"))
    degree = _blank_to_none(row.get("DGR"))
    conf_date = _parse_date(row.get("CONF_DT"), None)
    return {
        "mnts_id": extract_mnts_id(row.get("DOWN_URL")),
        "conf_id": _blank_to_none(row.get("CONF_ID")),
        "title": _special_title(comm_name, class_name, row.get("SESS"), degree, conf_date),
        "meeting_type": _special_meeting_type(endpoint),
        "class_name": class_name,
        "dae_num": 22,
        "session_no": session_no,
        "degree": degree,
        "conf_date": conf_date,
        "comm_name": comm_name,
        "comm_code": _blank_to_none(row.get("CMIT_CD")),
        "pdf_link_url": _blank_to_none(row.get("DOWN_URL")),
        "vod_link_url": None,
        "conf_link_url": None,
        "source_api": endpoint,
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
    if existing["source_api"] != meeting["source_api"]:
        _validate_duplicate_meeting(existing, meeting)
        existing["source_api"] = "multi"


def _validate_duplicate_meeting(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    if existing["conf_date"] != incoming["conf_date"]:
        raise RuntimeError(
            f"meeting duplicate date mismatch for {existing['mnts_id']}: "
            f"{existing['conf_date']} != {incoming['conf_date']}"
        )
    if existing.get("conf_id") and incoming.get("conf_id") and existing["conf_id"] != incoming["conf_id"]:
        raise RuntimeError(
            f"meeting duplicate conf_id mismatch for {existing['mnts_id']}: "
            f"{existing['conf_id']} != {incoming['conf_id']}"
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


def _dedupe_agenda_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
) -> dict[str, list[dict[str, Any]]]:
    rows_by_bill: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(_fetch_vconfbill_rows, bill_id): bill_id for bill_id in bill_ids}
        for future in as_completed(futures):
            rows_by_bill[futures[future]] = future.result()
    return rows_by_bill


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


def _replace_children_for_meetings(conn: Any, meeting_ids: list[int]) -> None:
    if not meeting_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = ANY(%s)", (meeting_ids,))
        cur.execute("DELETE FROM agenda_items WHERE meeting_id = ANY(%s)", (meeting_ids,))


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
