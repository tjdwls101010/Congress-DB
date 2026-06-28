"""외부 HTTP 호출 동시성 상한.

외부 국회 API 호출은 source별 worker 수가 달라도 같은 전역
상한을 공유한다. 호출자는 worker를 몇 개 만들지보다 이 상한을 넘지 않는다는
사실만 알면 된다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock

DEFAULT_HTTP_CONCURRENCY_LIMIT = 20
HTTP_CONCURRENCY_ENV = "CONGRESS_DB_HTTP_CONCURRENCY_LIMIT"

_semaphore_lock = Lock()
_semaphore: BoundedSemaphore | None = None
_semaphore_limit: int | None = None


def http_concurrency_limit() -> int:
    """환경 변수에서 외부 HTTP 전역 동시성 상한을 읽는다."""
    raw = os.environ.get(HTTP_CONCURRENCY_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_HTTP_CONCURRENCY_LIMIT
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError(f"{HTTP_CONCURRENCY_ENV} must be a positive integer") from exc
    if limit <= 0:
        raise ValueError(f"{HTTP_CONCURRENCY_ENV} must be a positive integer")
    return limit


def cap_worker_count(worker_count: int) -> int:
    """요청 worker 수를 외부 HTTP 전역 상한 이하로 낮춘다."""
    if worker_count <= 0:
        raise ValueError("worker_count must be positive")
    return min(worker_count, http_concurrency_limit())


def cap_worker_levels(levels: Sequence[int]) -> tuple[int, ...]:
    """benchmark 후보 worker 수를 전역 상한에 맞춰 중복 없이 정리한다."""
    capped = {cap_worker_count(int(level)) for level in levels}
    return tuple(sorted(capped))


@contextmanager
def external_http_slot() -> Iterator[None]:
    """전역 HTTP slot을 하나 점유한다."""
    semaphore = _current_semaphore()
    semaphore.acquire()
    try:
        yield
    finally:
        semaphore.release()


def _current_semaphore() -> BoundedSemaphore:
    global _semaphore, _semaphore_limit
    limit = http_concurrency_limit()
    with _semaphore_lock:
        if _semaphore is None or _semaphore_limit != limit:
            _semaphore = BoundedSemaphore(limit)
            _semaphore_limit = limit
        return _semaphore
