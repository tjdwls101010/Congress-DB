#!/usr/bin/env python3
"""Scrape National Assembly meeting minutes from the web into SQLite.

Fetches structured HTML from record.assembly.go.kr, extracts speaker utterances
with accurate metadata from DOM attributes, and detects Q&A session boundaries.

Usage:
    python scrape_minutes.py <db_path> <url1> [url2 ...]
    python scrape_minutes.py <db_path> --id 55553 55554
"""

# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "beautifulsoup4", "hanja"]
# ///

import sys
import re
import json
import sqlite3
import argparse
import unicodedata
from urllib.parse import urlparse, parse_qs

import hanja

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://record.assembly.go.kr/assembly/viewer/minutes/xml.do"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PRESIDER_SUFFIXES = ('의장', '부의장', '의장대리', '위원장', '부위원장', '위원장대리', '소위원장')
NON_RESPONDENT_TITLES = {'위원', '의원', '반장', '의사국장'}

_SUBCOMMITTEE_RE = re.compile(
    r'(?:소위원회|예산결산.*소위|조세소위|법안심사.*소위|안건조정위원회)'
)


def _is_chair(speaker_title):
    """의장/위원장 등 진행자인지 판별 (접미사 일치)."""
    return any(speaker_title.endswith(s) for s in PRESIDER_SUFFIXES)


def _is_respondent(speaker_title):
    """답변자(정부 관료 등)인지 판별. 진행자/의원은 제외."""
    if speaker_title in NON_RESPONDENT_TITLES:
        return False
    if _is_chair(speaker_title):
        return False
    return True


def _is_subcommittee(title):
    """회의 제목에서 소위원회 여부 판별."""
    if not title:
        return False
    return bool(_SUBCOMMITTEE_RE.search(title))


# ── DB Setup ──────────────────────────────────────────────────────────────

def ensure_tables(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transcripts_meetings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            mnts_id    INTEGER UNIQUE NOT NULL,
            title      TEXT NOT NULL,
            date       TEXT NOT NULL,
            url        TEXT,
            date_saved TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transcripts_session_groups (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id       INTEGER NOT NULL REFERENCES transcripts_meetings(id),
            questioner_name  TEXT NOT NULL,
            respondent_names TEXT,
            utterance_count  INTEGER NOT NULL DEFAULT 0,
            total_chars      INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transcripts_utterances (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id       INTEGER NOT NULL REFERENCES transcripts_meetings(id),
            session_group_id INTEGER REFERENCES transcripts_session_groups(id),
            sequence         INTEGER NOT NULL,
            speaker_name     TEXT NOT NULL,
            speaker_title    TEXT NOT NULL,
            content          TEXT NOT NULL,
            UNIQUE(meeting_id, sequence)
        );

        CREATE INDEX IF NOT EXISTS idx_utterances_meeting
            ON transcripts_utterances(meeting_id);
        CREATE INDEX IF NOT EXISTS idx_utterances_speaker
            ON transcripts_utterances(speaker_name);
        CREATE INDEX IF NOT EXISTS idx_session_groups_meeting
            ON transcripts_session_groups(meeting_id);
        CREATE INDEX IF NOT EXISTS idx_session_groups_questioner
            ON transcripts_session_groups(questioner_name);
    """)
    # Migrate: add columns if missing (for existing DBs)
    existing_cols = {
        r[1] for r in conn.execute(
            "PRAGMA table_info(transcripts_session_groups)"
        ).fetchall()
    }
    for col, defn in [
        ("utterance_count", "INTEGER NOT NULL DEFAULT 0"),
        ("total_chars", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in existing_cols:
            conn.execute(
                f"ALTER TABLE transcripts_session_groups ADD COLUMN {col} {defn}"
            )
    conn.commit()


# ── HTML Parsing ──────────────────────────────────────────────────────────

def parse_date(text):
    """Convert '2025년 10월 30일(목)' → '2025-10-30'."""
    m = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def parse_minutes(html, mnts_id, url):
    """Parse meeting HTML into structured data.

    Returns (meeting_info, utterances) where:
        meeting_info = dict with mnts_id, title, date, url
        utterances = list of (sequence, speaker_name, speaker_title, content)
    """
    soup = BeautifulSoup(html, 'html.parser')

    h2 = soup.find('h2')
    title = (h2.get_text(strip=True) if h2 else '') or f"회의록 {mnts_id}"

    date = None
    place = soup.select_one('.minutes_header .place')
    if place:
        for li in place.find_all('li'):
            sbj = li.select_one('.sbj')
            con = li.select_one('.con')
            if sbj and '일시' in sbj.get_text() and con:
                date = parse_date(con.get_text())
                break

    if not date:
        m = re.search(r'\((\d{4})\.(\d{2})\.(\d{2})\.\)', title)
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            date = "unknown"

    meeting_info = {
        'mnts_id': mnts_id,
        'title': title,
        'date': date,
        'url': url,
    }

    utterances = []
    seen_seqs = set()
    body = soup.select_one('.minutes_body')
    if not body:
        return meeting_info, utterances

    for div in body.find_all('div', class_='speaker'):
        div_id = div.get('id', '')
        m = re.match(r'spk_(\d+)', div_id)
        if not m:
            continue
        seq = int(m.group(1))

        if seq in seen_seqs:
            continue
        seen_seqs.add(seq)

        name = div.get('data-name', '').strip()
        # Convert Hanja names to Hangul (e.g. 李憲昇 → 이헌승)
        name = hanja.translate(unicodedata.normalize('NFKC', name), 'substitution')
        pos = div.get('data-pos', '').strip()
        if not name:
            continue

        talk = div.select_one('.talk .txt')
        if talk:
            spans = talk.find_all('span', class_='spk_sub')
            if spans:
                content = '\n'.join(s.get_text(strip=True) for s in spans)
            else:
                content = talk.get_text(strip=True)
        else:
            content = ''

        if content:
            utterances.append((seq, name, pos, content))

    return meeting_info, utterances


# ── Scraping ──────────────────────────────────────────────────────────────

def fetch_minutes(mnts_id):
    """Fetch meeting minutes HTML by mnts_id."""
    url = f"{BASE_URL}?id={mnts_id}&type=view"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text, url


def extract_id_from_url(url):
    """Extract mnts_id from a meeting minutes URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    ids = params.get('id', [])
    if ids:
        return int(ids[0])
    return None


# ── Session Group Detection (Memory-based) ───────────────────────────────


def _find_nominations_mem(utterances):
    """Find chair nominations from in-memory utterances list.

    Detects when a chair mentions a member's name and that member speaks next.
    Only members (의원/위원) are recognized as questioners.

    Args:
        utterances: [(seq, name, title, content), ...]

    Returns [(sequence, questioner_name)].
    """
    known_speakers = {name for _, name, _, _ in utterances}

    nominations = []
    for i, (seq, name, title, content) in enumerate(utterances):
        if not _is_chair(title):
            continue

        # Find next member (의원/위원) speaker
        next_speaker = None
        for j in range(i + 1, len(utterances)):
            if utterances[j][2] in ('위원', '의원'):
                next_speaker = utterances[j][1]
                break

        if not next_speaker or next_speaker not in known_speakers:
            continue

        if next_speaker in content:
            nominations.append((seq, next_speaker))

    return nominations


def _merge_consecutive(nominations):
    """Merge consecutive nominations of the same questioner."""
    if not nominations:
        return nominations
    merged = [nominations[0]]
    for seq, name in nominations[1:]:
        if name != merged[-1][1]:
            merged.append((seq, name))
    return merged


def detect_sessions_from_utterances(title, utterances):
    """Detect Q&A session boundaries from in-memory utterances (no DB).

    Args:
        title: meeting title (to check subcommittee)
        utterances: [(seq, name, title, content), ...]

    Returns list of dicts:
        [{"questioner": str, "respondents_json": str|None,
          "seq_start": int, "seq_end": int,
          "utterance_count": int, "total_chars": int}, ...]
    """
    if _is_subcommittee(title) or not utterances:
        return []

    nominations = _find_nominations_mem(utterances)
    nominations = _merge_consecutive(nominations)

    if not nominations:
        return []

    max_seq = max(u[0] for u in utterances)

    # Build seq→utterance lookup for respondent/stats computation
    by_seq = {u[0]: u for u in utterances}

    groups = []
    for i, (nom_seq, questioner) in enumerate(nominations):
        seq_start = nom_seq
        seq_end = nominations[i + 1][0] - 1 if i + 1 < len(nominations) else max_seq

        # Find respondents (government officials etc. — exclude chairs and members)
        respondents = sorted({
            f"{u[2]} {u[1]}"
            for u in utterances
            if seq_start <= u[0] <= seq_end and _is_respondent(u[2])
        })
        respondents_json = json.dumps(respondents, ensure_ascii=False) if respondents else None

        # Stats
        range_utts = [u for u in utterances if seq_start <= u[0] <= seq_end]
        utterance_count = len(range_utts)
        total_chars = sum(len(u[3]) for u in range_utts)

        groups.append({
            "questioner": questioner,
            "respondents_json": respondents_json,
            "seq_start": seq_start,
            "seq_end": seq_end,
            "utterance_count": utterance_count,
            "total_chars": total_chars,
        })

    return groups


# ── Session Group Detection (DB-based, for rebuild) ──────────────────────

def detect_session_groups(conn, meeting_id):
    """Detect Q&A session boundaries from DB data. Used by rebuild_session_groups.py.

    Returns number of groups created.
    """
    title = conn.execute(
        "SELECT title FROM transcripts_meetings WHERE id = ?",
        (meeting_id,)
    ).fetchone()[0]

    utterances = conn.execute(
        """SELECT sequence, speaker_name, speaker_title, content
           FROM transcripts_utterances
           WHERE meeting_id = ? ORDER BY sequence""",
        (meeting_id,)
    ).fetchall()

    groups = detect_sessions_from_utterances(title, utterances)

    for g in groups:
        cursor = conn.execute(
            """INSERT INTO transcripts_session_groups
               (meeting_id, questioner_name, respondent_names,
                utterance_count, total_chars)
               VALUES (?, ?, ?, ?, ?)""",
            (meeting_id, g["questioner"], g["respondents_json"],
             g["utterance_count"], g["total_chars"])
        )
        sg_id = cursor.lastrowid
        conn.execute(
            """UPDATE transcripts_utterances SET session_group_id = ?
               WHERE meeting_id = ? AND sequence BETWEEN ? AND ?""",
            (sg_id, meeting_id, g["seq_start"], g["seq_end"])
        )

    return len(groups)


# ── DB Insertion ──────────────────────────────────────────────────────────

def save_to_db(conn, meeting_info, utterances, session_groups=None):
    """Insert meeting, session_groups, and utterances in a single transaction.

    If session_groups is provided (from detect_sessions_from_utterances),
    uses pre-computed data. Otherwise falls back to DB-based detection.

    Returns (meeting_id, session_group_count), or (None, 0) if duplicate.
    """
    mnts_id = meeting_info['mnts_id']

    dup = conn.execute(
        "SELECT id FROM transcripts_meetings WHERE mnts_id = ?",
        (mnts_id,)
    ).fetchone()
    if dup:
        return None, 0

    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO transcripts_meetings (mnts_id, title, date, url)
           VALUES (?, ?, ?, ?)""",
        (meeting_info['mnts_id'], meeting_info['title'],
         meeting_info['date'], meeting_info['url'])
    )
    meeting_id = cursor.lastrowid

    if session_groups is None:
        # Fallback: insert utterances first, then detect from DB
        cursor.executemany(
            """INSERT INTO transcripts_utterances
               (meeting_id, sequence, speaker_name, speaker_title, content)
               VALUES (?, ?, ?, ?, ?)""",
            [(meeting_id, seq, name, t, content)
             for seq, name, t, content in utterances]
        )
        conn.commit()
        sg_count = detect_session_groups(conn, meeting_id)
        conn.commit()
        return meeting_id, sg_count

    # Pre-computed session groups: build seq→sg_id mapping
    sg_map = {}  # seq → sg_id
    for g in session_groups:
        cursor.execute(
            """INSERT INTO transcripts_session_groups
               (meeting_id, questioner_name, respondent_names,
                utterance_count, total_chars)
               VALUES (?, ?, ?, ?, ?)""",
            (meeting_id, g["questioner"], g["respondents_json"],
             g["utterance_count"], g["total_chars"])
        )
        sg_id = cursor.lastrowid
        for seq in range(g["seq_start"], g["seq_end"] + 1):
            sg_map[seq] = sg_id

    cursor.executemany(
        """INSERT INTO transcripts_utterances
           (meeting_id, session_group_id, sequence, speaker_name, speaker_title, content)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(meeting_id, sg_map.get(seq), seq, name, t, content)
         for seq, name, t, content in utterances]
    )

    conn.commit()
    return meeting_id, len(session_groups)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='국회회의록 웹 스크래핑 → SQLite DB'
    )
    parser.add_argument('db_path', help='SQLite DB 파일 경로')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('urls', nargs='*', default=[], help='회의록 URL')
    group.add_argument('--id', nargs='+', type=int, dest='ids',
                       help='회의록 ID (mnts_id)')
    args = parser.parse_args()

    mnts_ids = []
    if args.ids:
        mnts_ids = args.ids
    else:
        for url in args.urls:
            mid = extract_id_from_url(url)
            if mid:
                mnts_ids.append(mid)
            else:
                print(f"  ✗ URL에서 id를 추출할 수 없음: {url}", file=sys.stderr)

    if not mnts_ids:
        print("처리할 회의록이 없습니다.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(args.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_tables(conn)

    existing = set(
        r[0] for r in conn.execute(
            "SELECT mnts_id FROM transcripts_meetings"
        ).fetchall()
    )

    ok = 0
    skipped = 0
    failed = 0

    for mnts_id in mnts_ids:
        if mnts_id in existing:
            print(f"  - 스킵 (이미 존재): {mnts_id}")
            skipped += 1
            continue

        try:
            html, url = fetch_minutes(mnts_id)
            meeting_info, utterances = parse_minutes(html, mnts_id, url)

            if not utterances:
                print(f"  ✗ 발언을 찾을 수 없음: {mnts_id}", file=sys.stderr)
                failed += 1
                continue

            mid, sg_count = save_to_db(conn, meeting_info, utterances)
            if mid is None:
                print(f"  - 스킵 (중복 title+date): {meeting_info['title']}")
                skipped += 1
                continue
            sg_str = f", {sg_count} 세션" if sg_count else ""
            print(f"  ✓ {meeting_info['title']} ({meeting_info['date']}) — {len(utterances)}건{sg_str}")
            ok += 1

        except Exception as e:
            print(f"  ✗ {mnts_id}: {e}", file=sys.stderr)
            failed += 1

    conn.close()
    print(f"\n완료: {ok}건 저장, {skipped}건 스킵, {failed}건 실패")


if __name__ == "__main__":
    main()
