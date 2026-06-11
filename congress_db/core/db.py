"""Postgres 연결 유틸리티.

deep module 의도: psycopg 연결 생성·해제·환경 변수 읽기를 한 곳에서 흡수해서
호출자는 `with get_conn() as conn:` 또는 `with get_pooled_conn() as conn:` 한 줄만
알면 되도록 한다.

적재/restore는 직접 연결(`get_conn`)을 쓰고, 읽기/지속 작업은 pooler 호환
경로(`get_pooled_conn`)를 쓴다.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

# .env 파일이 있으면 환경 변수로 흡수. 파일 없으면 조용히 통과.
load_dotenv()
load_dotenv(".env.local", override=False)

_pool_lock = Lock()
_pool: ConnectionPool | None = None
_pool_config: tuple[str, int, int] | None = None


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


@contextmanager
def get_pooled_conn() -> Iterator[psycopg.Connection]:
    """읽기/지속 작업용 pooled Postgres 연결을 빌린다.

    `DATABASE_POOL_URL`이 있으면 우선 사용하고, 없으면 `DATABASE_URL`을 사용한다.
    Neon `-pooler`/PgBouncer transaction mode와 호환되도록 prepared statement를
    비활성화한다.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


@contextmanager
def get_readonly_conn() -> Iterator[psycopg.Connection]:
    """`CONGRESS_RO_URL`로 read-only Postgres에 연결한다.

    `CONGRESS_RO_URL`은 Neon pooled endpoint이므로 PgBouncer transaction mode와
    호환되도록 prepared statement를 비활성화한다. 읽기 전용 ops 리포트는
    transaction 경계를 가질 필요가 없어 autocommit으로 실행한다.

    Raises:
        KeyError: CONGRESS_RO_URL 환경변수가 없을 때.
        psycopg.OperationalError: DB가 기동되지 않았거나 접속 정보가 틀렸을 때.
    """
    url = os.environ["CONGRESS_RO_URL"]
    conn = psycopg.connect(url, autocommit=True, prepare_threshold=None)
    try:
        yield conn
    finally:
        conn.close()


def close_pool() -> None:
    """테스트와 장기 프로세스 종료 시 pooled connection을 닫는다."""
    global _pool, _pool_config
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool = None
        _pool_config = None


def _get_pool() -> ConnectionPool:
    global _pool, _pool_config
    conninfo = os.environ.get("DATABASE_POOL_URL") or os.environ["DATABASE_URL"]
    min_size = _pool_size("DATABASE_POOL_MIN_SIZE", 1)
    max_size = _pool_size("DATABASE_POOL_MAX_SIZE", 10)
    if min_size > max_size:
        raise ValueError("DATABASE_POOL_MIN_SIZE must be <= DATABASE_POOL_MAX_SIZE")

    config = (conninfo, min_size, max_size)
    with _pool_lock:
        if _pool is not None and _pool_config == config:
            return _pool
        if _pool is not None:
            _pool.close()
        _pool = ConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs={"prepare_threshold": None},
        )
        _pool_config = config
        return _pool


def _pool_size(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be a positive integer")
    return value


def execute_many(
    conn: psycopg.Connection,
    sql: str,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    """같은 SQL을 여러 parameter row에 실행한다.

    호출자는 트랜잭션 경계(commit/rollback)를 직접 소유한다.
    """
    batch = list(rows)
    if not batch:
        return 0

    with conn.cursor() as cur:
        cur.executemany(sql, batch)
    return len(batch)
