#!/usr/bin/env python3
"""
국회 법안 조회 → SQLite DB 저장 스크립트 (스트리밍 방식)

페이지 단위로 즉시 DB에 저장하여, 중간 실패 시에도 진행분이 보존된다.
신규 법안만 summary를 병렬 조회하고, 기존 법안은 메타데이터만 업데이트한다.

사용법:
    python fetch_bills.py congress.db --age 22
    python fetch_bills.py congress.db --member 백승아
    python fetch_bills.py congress.db --workers 30
"""

import argparse
import json
import sqlite3
from typing import Dict, List, Optional
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    from urllib import request, parse
except ImportError:
    import urllib.request as request
    import urllib.parse as parse


class BillFetcher:
    """국회 법안 정보 조회 및 DB 저장 클래스"""

    BILLS_API = "https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn"
    SUMMARY_API = "https://open.assembly.go.kr/portal/openapi/BPMBILLSUMMARY"
    API_KEY = "7d7811f4377240bca05c93c6a30755f8"

    def __init__(self, age: int = 22, member_name: Optional[str] = None):
        self.member_name = member_name
        self.proposer = f"{member_name}의원" if member_name else None
        self.age = str(age)

    def _fetch_page(self, page_index: int, page_size: int = 100) -> tuple[List[Dict], int]:
        """API에서 법안 목록 1페이지를 조회합니다. (rows, total_count) 반환."""
        params = {
            "Key": self.API_KEY,
            "Type": "json",
            "pIndex": str(page_index),
            "pSize": str(page_size),
            "AGE": self.age,
        }
        if self.proposer:
            params["PROPOSER"] = self.proposer

        query_string = "&".join([f"{k}={parse.quote(str(v))}" for k, v in params.items()])
        url = f"{self.BILLS_API}?{query_string}"

        req = request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        with request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))

        if not data:
            return [], 0

        result = data.get("nzmimeepazxkubdpn", [{}])
        if not result:
            return [], 0

        total_count = 0
        head = result[0].get("head", [{}])
        if head:
            total_count = int(head[0].get("list_total_count", 0))

        row_data = result[1].get("row", []) if len(result) > 1 else []
        return row_data, total_count

    def fetch_summary(self, bill_no: str) -> Optional[str]:
        """법안의 주요내용을 조회합니다."""
        params = {
            "Key": self.API_KEY,
            "Type": "json",
            "pIndex": "1",
            "pSize": "10",
            "BILL_NO": bill_no
        }
        try:
            query_string = "&".join([f"{k}={parse.quote(str(v))}" for k, v in params.items()])
            url = f"{self.SUMMARY_API}?{query_string}"
            req = request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            with request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
            result = data.get("BPMBILLSUMMARY", [{}])
            if len(result) > 1:
                row_data = result[1].get("row", [])
                if row_data:
                    return row_data[0].get("SUMMARY", None)
            return None
        except Exception as e:
            print(f"  summary 조회 실패 ({bill_no}): {e}")
            return None

    def _ensure_table(self, conn):
        """bills 테이블이 없으면 생성합니다."""
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bills (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_no       TEXT    UNIQUE NOT NULL,
                bill_name     TEXT    NOT NULL,
                proposer      TEXT    NOT NULL,
                propose_dt    TEXT,
                committee     TEXT,
                proc_result   TEXT,
                co_proposers  TEXT,
                summary       TEXT,
                assembly      INTEGER NOT NULL,
                fetched_at    TEXT    DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.commit()

    def _process_page(self, conn, bills: List[Dict], existing: set, workers: int) -> tuple[int, int]:
        """한 페이지의 법안을 처리합니다. (new_count, update_count) 반환."""
        # 의원 지정 시 대표발의만 필터링
        if self.member_name:
            bills = [b for b in bills if self.member_name in b.get("RST_PROPOSER", "")]

        new_bills = []
        update_count = 0

        for bill in bills:
            bill_no = bill.get("BILL_NO", "")
            if bill_no in existing:
                conn.execute("""
                    UPDATE bills SET proc_result=?, committee=?, fetched_at=datetime('now','localtime')
                    WHERE bill_no=?
                """, (bill.get("PROC_RESULT"), bill.get("COMMITTEE"), bill_no))
                update_count += 1
            else:
                new_bills.append(bill)

        if update_count:
            conn.commit()

        if not new_bills:
            return 0, update_count

        # 신규 법안: summary 병렬 조회
        summaries = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.fetch_summary, b["BILL_NO"]): b["BILL_NO"] for b in new_bills}
            for f in as_completed(futures):
                bill_no = futures[f]
                try:
                    summaries[bill_no] = f.result()
                except Exception:
                    summaries[bill_no] = None

        # DB INSERT
        for bill in new_bills:
            bill_no = bill.get("BILL_NO", "")
            conn.execute("""
                INSERT INTO bills (bill_no, bill_name, proposer, propose_dt, committee, proc_result, co_proposers, summary, assembly)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bill_no,
                bill.get("BILL_NAME", ""),
                bill.get("RST_PROPOSER", self.member_name or ""),
                bill.get("PROPOSE_DT", ""),
                bill.get("COMMITTEE", None),
                bill.get("PROC_RESULT", None),
                bill.get("PUBL_PROPOSER", ""),
                summaries.get(bill_no),
                int(self.age)
            ))
            existing.add(bill_no)

        conn.commit()
        return len(new_bills), update_count

    def run(self, db_path: str, workers: int = 20):
        """페이지 단위로 조회 → 즉시 DB 저장을 반복합니다."""
        conn = sqlite3.connect(db_path)
        self._ensure_table(conn)

        existing = {r[0] for r in conn.execute("SELECT bill_no FROM bills").fetchall()}
        if existing:
            print(f"DB 기존 법안: {len(existing)}건")

        label = f"'{self.member_name}' 의원의 " if self.member_name else ""
        print(f"{label}제{self.age}대 법안 수집 시작 (workers={workers})")

        page = 1
        total_count = 0
        total_new = 0
        total_update = 0
        start_time = time.time()

        while True:
            try:
                rows, api_total = self._fetch_page(page)
            except Exception as e:
                print(f"  페이지 {page} 조회 실패: {e}")
                break

            if page == 1:
                total_count = api_total
                print(f"API 전체 법안: {total_count}건")

            if not rows:
                break

            new, updated = self._process_page(conn, rows, existing, workers)
            total_new += new
            total_update += updated

            fetched_so_far = min(page * 100, total_count)
            elapsed = time.time() - start_time
            print(f"  페이지 {page} — {fetched_so_far}/{total_count} | 신규 {new}건 | 업데이트 {updated}건 | {elapsed:.0f}초")

            if len(rows) < 100:
                break

            page += 1
            time.sleep(0.5)

        conn.close()
        elapsed = time.time() - start_time

        print(f"\n✓ 완료: {db_path} ({elapsed:.0f}초)")
        print(f"  - 신규 추가: {total_new}건")
        print(f"  - 업데이트: {total_update}건")


def main():
    parser = argparse.ArgumentParser(description="국회 법안 조회 → SQLite DB 저장")
    parser.add_argument("db_path", help="SQLite DB 파일 경로")
    parser.add_argument("--member", help="의원명. 생략 시 전체 법률안 수집")
    parser.add_argument("--age", type=int, default=22, help="국회 대수 (기본: 22)")
    parser.add_argument("--workers", type=int, default=20, help="summary 병렬 조회 스레드 수 (기본: 20)")

    args = parser.parse_args()
    fetcher = BillFetcher(age=args.age, member_name=args.member)
    fetcher.run(args.db_path, workers=args.workers)


if __name__ == "__main__":
    main()
