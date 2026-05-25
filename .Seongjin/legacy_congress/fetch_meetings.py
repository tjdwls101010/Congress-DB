#!/usr/bin/env python3
"""Fetch new meetings via the National Assembly API and scrape them.

Queries open APIs for committee and/or plenary meeting records, identifies
meetings not yet in the DB, and scrapes their full transcripts in parallel.

Usage:
    python fetch_meetings.py <db_path> --committee 과학기술정보방송통신위원회
    python fetch_meetings.py <db_path> --all --since 2024
    python fetch_meetings.py <db_path> --all --since 2024 --workers 8
"""

# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "beautifulsoup4", "hanja"]
# ///

import sys
import os
import re
import time
import sqlite3
import argparse
from collections import defaultdict
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(__file__))
from scrape_minutes import ensure_tables, fetch_minutes, parse_minutes, save_to_db, detect_sessions_from_utterances

API_BASE = "https://open.assembly.go.kr/portal/openapi"
API_KEY = "7d7811f4377240bca05c93c6a30755f8"
USER_AGENT = "Mozilla/5.0"

APIS = {
    "committee": {
        "endpoint": "ncwgseseafwbuheph",
        "label": "위원회 회의록",
        "committee_field": "COMM_NAME",
    },
    "plenary": {
        "endpoint": "nzbyfwhwaoanttzje",
        "label": "본회의 회의록",
        "committee_field": None,
    },
}


def _date_range(since):
    """Generate CONF_DATE values from since year to current year.

    "2024" → ["2024", "2025", "2026"]
    "2025-03" → ["2025-03"]
    None → [None]
    """
    if not since:
        return [None]
    if len(since) > 4:
        return [since]
    start_year = int(since[:4])
    end_year = date.today().year
    return [str(y) for y in range(start_year, end_year + 1)]


def fetch_meeting_list(api_key, since=None, age=22, committee=None):
    """Fetch meeting CONFER_NUMs from a given API across date range."""
    api = APIS[api_key]
    endpoint = api["endpoint"]
    meetings = {}

    for conf_date in _date_range(since):
        page = 1
        while True:
            params = {
                "Key": API_KEY,
                "Type": "json",
                "pIndex": page,
                "pSize": 1000,
                "DAE_NUM": age,
            }
            if conf_date:
                params["CONF_DATE"] = conf_date

            resp = requests.get(
                f"{API_BASE}/{endpoint}",
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if "RESULT" in data:
                break

            rows = data[endpoint][1]["row"]
            total = data[endpoint][0]["head"][0]["list_total_count"]

            for row in rows:
                cn = row["CONFER_NUM"]
                if committee and api["committee_field"]:
                    comm = row.get(api["committee_field"], "")
                    if committee not in comm:
                        continue
                if cn not in meetings:
                    meetings[cn] = {
                        "mnts_id": cn,
                        "title": row["TITLE"],
                        "date": row["CONF_DATE"],
                    }

            if page * 1000 >= total:
                break
            page += 1

    return sorted(meetings.values(), key=lambda m: m["date"])


_TITLE_RE = re.compile(
    r"제(\d+)회\s*(?:국회)?\s*(?:\(([^)]+)\))?.*?제(\d+)차\s*(.+?)(?:\s*\(|$)"
)
_FINGERPRINT_RE = re.compile(r"제(\d+)회.*?제(\d+)차")
_DATE_RE = re.compile(r"(\d{4})[.\-년]?\s*(\d{1,2})[.\-월]?\s*(\d{1,2})")


def _fingerprint(text):
    """Return (assembly_session, 차수) from a title, or None."""
    if not text:
        return None
    m = _FINGERPRINT_RE.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _date_key(text):
    """Return (yyyy, mm, dd) from any date-like substring in text."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def report_missing_sequences(meetings):
    """Detect gaps in (회기, 회차계열) sequences and print a warning.

    Groups by (assembly_session, session_kind, series_label), e.g.
    (429, "정기회", "국회본회의"), and reports missing 차 numbers.
    """
    groups = defaultdict(list)
    for m in meetings:
        title = m.get("title", "")
        match = _TITLE_RE.search(title)
        if not match:
            continue
        sess, kind, cha, label = match.groups()
        label = label.strip()
        kind = kind or ""
        groups[(int(sess), kind, label)].append((int(cha), m))

    warnings = []
    for (sess, kind, label), entries in groups.items():
        chas = sorted({c for c, _ in entries})
        if len(chas) < 2:
            continue
        full = set(range(chas[0], chas[-1] + 1))
        missing = sorted(full - set(chas))
        if missing:
            warnings.append(
                f"⚠ 누락 가능성 — 제{sess}회 ({kind}) {label}: "
                f"제{', '.join(str(c) for c in missing)}차 미수집"
            )
    if warnings:
        print()
        for w in warnings:
            print(w)


def _format_id_sample(meetings, n=5):
    """Return short sample of mnts_ids for visibility, e.g. '[55274, 55334, ...]'."""
    if not meetings:
        return "[]"
    ids = [str(m["mnts_id"]) for m in meetings[:n]]
    extra = len(meetings) - n
    suffix = f", ... +{extra}" if extra > 0 else ""
    return f"[{', '.join(ids)}{suffix}]"


def _scrape_one(mnts_id):
    """Scrape a single meeting with in-memory session detection.

    Returns (mnts_id, meeting_info, utterances, session_groups).
    """
    html, url = fetch_minutes(mnts_id)
    meeting_info, utterances = parse_minutes(html, mnts_id, url)
    session_groups = detect_sessions_from_utterances(meeting_info['title'], utterances)
    return mnts_id, meeting_info, utterances, session_groups


def scrape_new_meetings(conn, meetings, existing, workers=1, refresh=False):
    """Scrape and save meetings not in existing set. Returns (ok, skipped).

    When refresh=True, existing rows for the given mnts_ids are replaced
    (delete utterances/session_groups/meeting then re-insert) so that
    previously partial or mis-mapped data is overwritten.
    """
    ok = 0
    skipped = 0
    total = len(meetings)

    def _purge(mnts_id):
        row = conn.execute(
            "SELECT id FROM transcripts_meetings WHERE mnts_id=?",
            (mnts_id,),
        ).fetchone()
        if not row:
            return
        meeting_id = row[0]
        conn.execute("DELETE FROM transcripts_utterances WHERE meeting_id=?", (meeting_id,))
        conn.execute("DELETE FROM transcripts_session_groups WHERE meeting_id=?", (meeting_id,))
        conn.execute("DELETE FROM transcripts_meetings WHERE id=?", (meeting_id,))
        conn.commit()
        existing.discard(mnts_id)

    def _handle_result(meeting, meeting_info, utterances, session_groups=None):
        nonlocal ok, skipped
        if not meeting_info['title'] or meeting_info['title'].startswith('회의록 '):
            meeting_info['title'] = meeting.get('title', meeting_info['title'])

        # Sanity check: API metadata vs scraped body must agree on 회기/차수.
        # Server occasionally serves stale content for a given mnts_id, which
        # historically poisoned the DB with mis-mapped rows.
        api_fp = _fingerprint(meeting.get('title', ''))
        body_fp = _fingerprint(meeting_info.get('title', ''))
        if api_fp and body_fp and api_fp != body_fp:
            print(
                f"  [{ok+skipped+1}/{total}] ✗ 본문 불일치 (API={api_fp}, 본문={body_fp}): "
                f"mnts_id={meeting_info['mnts_id']}",
                file=sys.stderr,
            )
            skipped += 1
            return

        if not utterances:
            print(f"  [{ok+skipped+1}/{total}] ✗ 발언 없음: {meeting['title']}", file=sys.stderr)
            skipped += 1
            return
        if len(utterances) < 20:
            print(f"  [{ok+skipped+1}/{total}] ⚠ 요약본 가능성: {meeting['title']} ({len(utterances)}건)")
        if refresh:
            _purge(meeting_info['mnts_id'])
        mid, sg_count = save_to_db(conn, meeting_info, utterances, session_groups)
        if mid is None:
            print(f"  [{ok+skipped+1}/{total}] - 스킵 (중복): {meeting['title']}")
            skipped += 1
            return
        sg_str = f", {sg_count} 세션" if sg_count else ""
        print(f"  [{ok+skipped+1}/{total}] ✓ {meeting_info['title']} ({meeting_info['date']}) — {len(utterances)}건{sg_str}")
        existing.add(meeting_info['mnts_id'])
        ok += 1

    if workers <= 1:
        for meeting in meetings:
            try:
                _, meeting_info, utterances, session_groups = _scrape_one(meeting["mnts_id"])
                _handle_result(meeting, meeting_info, utterances, session_groups)
            except Exception as e:
                print(f"  [{ok+skipped+1}/{total}] ✗ {meeting['mnts_id']}: {e}", file=sys.stderr)
                skipped += 1
        return ok, skipped

    # Parallel scraping + session detection, sequential DB writes
    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for meeting in meetings:
            f = pool.submit(_scrape_one, meeting["mnts_id"])
            futures[f] = meeting

        for f in as_completed(futures):
            meeting = futures[f]
            try:
                _, meeting_info, utterances, session_groups = f.result()
                _handle_result(meeting, meeting_info, utterances, session_groups)
            except Exception as e:
                print(f"  [{ok+skipped+1}/{total}] ✗ {meeting['mnts_id']}: {e}", file=sys.stderr)
                skipped += 1

    return ok, skipped


def main():
    parser = argparse.ArgumentParser(
        description="국회 API로 새 회의록 자동 수집"
    )
    parser.add_argument("db_path", help="SQLite DB 파일 경로")
    parser.add_argument(
        "--committee", help="위원회명 (예: 과학기술정보방송통신위원회)"
    )
    parser.add_argument(
        "--plenary", action="store_true", help="본회의 회의록도 수집"
    )
    parser.add_argument(
        "--all", action="store_true", dest="fetch_all",
        help="모든 위원회 + 본회의 회의록 수집"
    )
    parser.add_argument(
        "--since", help="조회 시작 연도 (예: 2024, 2025-03)"
    )
    parser.add_argument(
        "--age", type=int, default=22, help="국회 대수 (기본: 22)"
    )
    parser.add_argument(
        "--workers", type=int, default=100,
        help="병렬 스크래핑 스레드 수 (기본: 100)"
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="DB에 이미 있는 mnts_id도 재조회하여 누락 발언 백필"
    )
    args = parser.parse_args()

    if args.fetch_all:
        args.committee = ""
        args.plenary = True

    if not args.committee and not args.plenary:
        parser.error("--committee, --plenary, --all 중 하나 이상 지정 필요")

    if args.committee and ("본회의" in args.committee or args.committee.lower() == "plenary"):
        parser.error(
            "본회의는 --plenary 또는 --all 옵션을 사용하세요. "
            "(--committee는 위원회 회의록 API 전용)"
        )

    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_tables(conn)

    existing = set(
        r[0] for r in conn.execute(
            "SELECT mnts_id FROM transcripts_meetings"
        ).fetchall()
    )

    total_ok = 0
    total_skipped = 0

    if args.committee is not None:
        label = args.committee or "전체"
        print(f"[위원회] {label} (since={args.since or '전체'})")
        api_meetings = fetch_meeting_list("committee", args.since, args.age, args.committee)
        if args.refresh:
            target = api_meetings
            print(f"  API: {len(api_meetings)}개 발견 {_format_id_sample(api_meetings)}, refresh 모드")
        else:
            target = [m for m in api_meetings if m["mnts_id"] not in existing]
            print(f"  API: {len(api_meetings)}개 발견 {_format_id_sample(api_meetings)}, 새 회의: {len(target)}개")
        report_missing_sequences(api_meetings)
        if target:
            ok, skip = scrape_new_meetings(conn, target, existing, args.workers, refresh=args.refresh)
            total_ok += ok
            total_skipped += skip

    if args.plenary:
        print(f"[본회의] (since={args.since or '전체'})")
        api_meetings = fetch_meeting_list("plenary", args.since, args.age)
        if args.refresh:
            target = api_meetings
            print(f"  API: {len(api_meetings)}개 발견 {_format_id_sample(api_meetings)}, refresh 모드")
        else:
            target = [m for m in api_meetings if m["mnts_id"] not in existing]
            print(f"  API: {len(api_meetings)}개 발견 {_format_id_sample(api_meetings)}, 새 회의: {len(target)}개")
        report_missing_sequences(api_meetings)
        if target:
            ok, skip = scrape_new_meetings(conn, target, existing, args.workers, refresh=args.refresh)
            total_ok += ok
            total_skipped += skip

    conn.close()

    if total_ok or total_skipped:
        print(f"\n완료: {total_ok}건 저장, {total_skipped}건 스킵")
    else:
        print("\n모든 회의가 이미 저장되어 있습니다.")


if __name__ == "__main__":
    main()
