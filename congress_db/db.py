"""Postgres 연결 유틸리티.

deep module 의도: psycopg 연결 생성·해제·환경 변수 읽기를 한 곳에서 흡수해서
호출자는 `with get_conn() as conn:` 한 줄만 알면 되도록 한다.

연결 풀과 `execute_many` 같은 대량 적재용 인터페이스는 실제 호출자가 생기는
슬라이스(#4 의원 적재)에서 필요해질 때 추가한다 (Slice 1에는 호출자가 없어
미리 만들지 않음).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

# .env 파일이 있으면 환경 변수로 흡수. 파일 없으면 조용히 통과.
load_dotenv()


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """`DATABASE_URL`로 Postgres에 연결하고 종료 시 닫는다.

    Raises:
        KeyError: DATABASE_URL 환경변수가 없을 때.
        psycopg.OperationalError: DB가 기동되지 않았거나 접속 정보가 틀렸을 때.
    """
    url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(url)
    try:
        yield conn
    finally:
        conn.close()
