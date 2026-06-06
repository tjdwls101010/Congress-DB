"""국회회의록 웹 목록 크롤러.

이 module의 interface는 `crawl_minutes_web_list()` 하나에 가깝게 유지한다.
호출자는 국회 웹 목록의 세부 async DOM 구조를 몰라도, HTML 회의록 대상 row를
정규화된 값으로 받을 수 있어야 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

from ..core.meeting_id import extract_mnts_id

BASE_ORIGIN = "https://record.assembly.go.kr"
LIST_PATH = "/assembly/mnts/total/22.do"
ASYNC_BASE = f"{BASE_ORIGIN}/assembly/mnts/async"
DETAIL_SELECTOR = 'a[href*="/assembly/viewer/minutes/xml.do"][href*="type=view"]'
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass(frozen=True)
class MinutesClassSpec:
    """웹 목록의 상위 회의 유형 탭."""

    class_id: int
    label: str
    meeting_type: str
    default_comm_name: str | None = None


@dataclass(frozen=True)
class MinutesWebListMeeting:
    """웹 목록에서 발견한 HTML 회의록 대상."""

    mnts_id: int
    title: str
    meeting_type: str
    conf_date: date
    comm_name: str | None
    session_no: int | None
    degree: str | None
    is_temporary: bool
    is_appendix: bool
    detail_url: str
    source_class_id: int
    source_class_label: str


@dataclass(frozen=True)
class HtmlUnavailableMinutes:
    """웹 목록에는 있으나 `type=view` HTML 링크가 없는 회의록 row."""

    mnts_id: int
    title: str
    source_class_id: int
    source_class_label: str


@dataclass(frozen=True)
class MinutesWebListCrawlResult:
    """웹 목록 크롤 결과."""

    meetings: tuple[MinutesWebListMeeting, ...]
    html_unavailable: tuple[HtmlUnavailableMinutes, ...]


CLASS_SPECS: tuple[MinutesClassSpec, ...] = (
    MinutesClassSpec(1, "국회본회의", "본회의"),
    MinutesClassSpec(2, "상임위원회", "상임위"),
    MinutesClassSpec(4, "예산결산특별위원회", "특별위", "예산결산특별위원회"),
    MinutesClassSpec(3, "특별위원회", "특별위"),
    MinutesClassSpec(5, "국정감사", "국정감사"),
    MinutesClassSpec(6, "국정조사", "국정조사"),
)


def crawl_minutes_web_list(
    *,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> tuple[MinutesWebListMeeting, ...]:
    """22대 전체회의록 웹 목록의 모든 `type=view` HTML 회의록을 수집한다."""
    return collect_minutes_web_list(session=session, timeout=timeout).meetings


def collect_minutes_web_list(
    *,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> MinutesWebListCrawlResult:
    """22대 웹 목록을 수집하고 HTML viewer가 없는 row도 별도 반환한다."""
    client = session or requests.Session()
    if hasattr(client, "headers"):
        client.headers.update({"User-Agent": USER_AGENT})

    meetings: dict[int, MinutesWebListMeeting] = {}
    html_unavailable: dict[int, HtmlUnavailableMinutes] = {}
    for spec in CLASS_SPECS:
        entry_url = _entry_url(spec.class_id)
        html = _get(client, entry_url, timeout=timeout)
        result = _crawl_class(client, spec, html, entry_url=entry_url, timeout=timeout)
        for meeting in result.meetings:
            meetings[meeting.mnts_id] = _merge_duplicate(meetings.get(meeting.mnts_id), meeting)
        for unavailable in result.html_unavailable:
            html_unavailable[unavailable.mnts_id] = unavailable
    return MinutesWebListCrawlResult(
        meetings=tuple(meetings[mnts_id] for mnts_id in sorted(meetings)),
        html_unavailable=tuple(html_unavailable[mnts_id] for mnts_id in sorted(html_unavailable)),
    )


def web_meeting_to_row(meeting: MinutesWebListMeeting) -> dict[str, Any]:
    """`meetings` upsert SQL에 넣을 수 있는 row로 변환한다."""
    return {
        "mnts_id": meeting.mnts_id,
        "title": meeting.title,
        "meeting_type": meeting.meeting_type,
        "session_no": meeting.session_no,
        "degree": meeting.degree,
        "conf_date": meeting.conf_date,
        "comm_name": meeting.comm_name,
        "is_temporary": meeting.is_temporary,
        "is_appendix": meeting.is_appendix,
    }


def _crawl_class(
    client: requests.Session,
    spec: MinutesClassSpec,
    html: str,
    *,
    entry_url: str,
    timeout: int,
) -> MinutesWebListCrawlResult:
    soup = BeautifulSoup(html, "html.parser")
    meetings: list[MinutesWebListMeeting] = []
    html_unavailable: list[HtmlUnavailableMinutes] = []
    if spec.class_id in {1, 4}:
        for session_anchor in soup.select("a.tit.sess"):
            response = _post(client, "sess.do", _sess_payload(session_anchor), entry_url, timeout=timeout)
            result = _parse_final_rows(
                response,
                spec,
                comm_name=spec.default_comm_name,
            )
            meetings.extend(result.meetings)
            html_unavailable.extend(result.html_unavailable)
        return MinutesWebListCrawlResult(tuple(meetings), tuple(html_unavailable))

    for committee_anchor in soup.select("a.tit.cmit"):
        comm_name = _clean_text(committee_anchor.get_text(" ", strip=True)) or spec.default_comm_name
        response = _post(client, "sessCmit.do", _sess_cmit_payload(committee_anchor), entry_url, timeout=timeout)
        child_soup = BeautifulSoup(response, "html.parser")
        for child_anchor in child_soup.select("a.tit.sub"):
            child_response = _post(client, "cmit.do", _cmit_payload(child_anchor), entry_url, timeout=timeout)
            result = _parse_final_rows(
                child_response,
                spec,
                comm_name=comm_name,
            )
            meetings.extend(result.meetings)
            html_unavailable.extend(result.html_unavailable)
    return MinutesWebListCrawlResult(tuple(meetings), tuple(html_unavailable))


def _parse_final_rows(
    html: str,
    spec: MinutesClassSpec,
    *,
    comm_name: str | None,
) -> MinutesWebListCrawlResult:
    soup = BeautifulSoup(html, "html.parser")
    meetings: list[MinutesWebListMeeting] = []
    html_unavailable: list[HtmlUnavailableMinutes] = []
    for title_anchor in soup.select("a[data-id]"):
        row = title_anchor.find_parent("li") or title_anchor.parent
        if row is None:
            continue
        detail_link = row.select_one(DETAIL_SELECTOR)
        is_appendix = _has_appendix_marker(row)
        title = _row_title(title_anchor, is_appendix=is_appendix)
        if detail_link is None:
            html_unavailable.append(
                HtmlUnavailableMinutes(
                    mnts_id=extract_mnts_id(title_anchor.get("data-id")),
                    title=title,
                    source_class_id=spec.class_id,
                    source_class_label=spec.label,
                )
            )
            continue

        mnts_id = extract_mnts_id(detail_link.get("href"))
        is_temporary = _has_temporary_marker(row)
        meetings.append(
            MinutesWebListMeeting(
                mnts_id=mnts_id,
                title=title,
                meeting_type=_meeting_type(spec, title, comm_name),
                conf_date=_parse_conf_date(title),
                comm_name=comm_name,
                session_no=_int_or_none(title_anchor.get("data-sess")),
                degree=_parse_degree(title),
                is_temporary=is_temporary,
                is_appendix=is_appendix,
                detail_url=urljoin(BASE_ORIGIN, str(detail_link.get("href"))),
                source_class_id=spec.class_id,
                source_class_label=spec.label,
            )
        )
    return MinutesWebListCrawlResult(tuple(meetings), tuple(html_unavailable))


def _entry_url(class_id: int) -> str:
    query = urlencode({"class_id_sch": str(class_id), "cmit_chk": "all"})
    return f"{BASE_ORIGIN}{LIST_PATH}?{query}"


def _get(client: requests.Session, url: str, *, timeout: int) -> str:
    response = client.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def _post(
    client: requests.Session,
    endpoint: str,
    payload: dict[str, str],
    referer: str,
    *,
    timeout: int,
) -> str:
    response = client.post(
        f"{ASYNC_BASE}/{endpoint}",
        data=payload,
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": referer},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def _sess_payload(anchor: Any) -> dict[str, str]:
    return {
        "th_sch": _data(anchor, "th"),
        "class_id_sch": _data(anchor, "class"),
        "sess_sch": _data(anchor, "sess"),
        "chk": _data(anchor, "chk1"),
        "cmit_chk_cmit": _data(anchor, "chk2"),
        "cmit_chk_sub": _data(anchor, "chk3"),
        "mnts_id_sch": _data(anchor, "id"),
        "mnts_year_sch": _data(anchor, "year"),
    }


def _sess_cmit_payload(anchor: Any) -> dict[str, str]:
    return {
        "council_cd_sch": _data(anchor, "cl"),
        "th_sch": _data(anchor, "th"),
        "sess_sch": _data(anchor, "sess"),
        "class_id_sch": _data(anchor, "class"),
        "cmit_id_sch": _data(anchor, "cmit"),
        "cmit_chk": _data(anchor, "chk1"),
        "cmit_chk_cmit": _data(anchor, "chk2"),
        "cmit_chk_sub": _data(anchor, "chk3"),
        "cmit_chk_etc": _data(anchor, "chk4"),
        "mnts_year_sch": _data(anchor, "year"),
    }


def _cmit_payload(anchor: Any) -> dict[str, str]:
    return {
        "council_cd_sch": _data(anchor, "cl"),
        "th_sch": _data(anchor, "th"),
        "class_id_sch": _data(anchor, "class"),
        "sess_sch": _data(anchor, "sess"),
        "cmit_cd_sch": _data(anchor, "cmitcd"),
        "cmit_chk": _data(anchor, "chk1"),
        "cmit_chk_cmit": _data(anchor, "chk2"),
        "cmit_chk_sub": _data(anchor, "chk3"),
        "cmit_chk_etc": _data(anchor, "chk4"),
        "mnts_id_sch": _data(anchor, "id"),
        "conf_year": _data(anchor, "dt"),
    }


def _data(anchor: Any, key: str) -> str:
    return str(anchor.get(f"data-{key}") or "").strip()


def _row_title(anchor: Any, *, is_appendix: bool) -> str:
    title = str(anchor.get("title") or "").strip()
    if not title:
        title = _clean_text(anchor.get_text(" ", strip=True))
    if is_appendix and "(부록)" not in title:
        title = f"{title} (부록)"
    return title


def _meeting_type(spec: MinutesClassSpec, title: str, comm_name: str | None) -> str:
    if spec.class_id == 2 and ("소위원회" in title or "소위원회" in str(comm_name or "")):
        return "소위원회"
    return spec.meeting_type


def _parse_conf_date(value: str) -> date:
    match = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", value)
    if not match:
        raise ValueError(f"cannot parse minutes web-list date from {value!r}")
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def _parse_degree(value: str) -> str | None:
    match = re.search(r"제\s*\d+\s*차|개회식", value)
    return match.group(0).replace(" ", "") if match else None


def _has_temporary_marker(row: Any) -> bool:
    return bool(row.select_one(".temp")) or "[임시]" in row.get_text(" ", strip=True)


def _has_appendix_marker(row: Any) -> bool:
    return bool(row.select_one(".btn_appendix")) or "(부록)" in row.get_text(" ", strip=True)


def _int_or_none(value: Any) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdecimal() else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _merge_duplicate(
    existing: MinutesWebListMeeting | None,
    incoming: MinutesWebListMeeting,
) -> MinutesWebListMeeting:
    if existing is None:
        return incoming
    if existing.conf_date != incoming.conf_date:
        raise ValueError(
            f"duplicate mnts_id date mismatch for {incoming.mnts_id}: "
            f"{existing.conf_date} != {incoming.conf_date}"
        )
    return MinutesWebListMeeting(
        mnts_id=existing.mnts_id,
        title=existing.title,
        meeting_type=existing.meeting_type,
        conf_date=existing.conf_date,
        comm_name=existing.comm_name or incoming.comm_name,
        session_no=existing.session_no or incoming.session_no,
        degree=existing.degree or incoming.degree,
        is_temporary=existing.is_temporary or incoming.is_temporary,
        is_appendix=existing.is_appendix or incoming.is_appendix,
        detail_url=existing.detail_url,
        source_class_id=existing.source_class_id,
        source_class_label=existing.source_class_label,
    )
