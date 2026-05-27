"""dead letter 재처리 workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .db import get_conn
from .ingest_state import finish_run, record_dead_letter, resolve_dead_letter, start_run


@dataclass(frozen=True)
class DeadLetterItem:
    """재처리 대상 dead letter."""

    id: int
    run_id: int
    source: str
    stage: str
    item_key: str
    payload: Mapping[str, Any]
    error: str
    attempts: int
    status: str
    first_failed_at: datetime
    last_failed_at: datetime


@dataclass(frozen=True)
class DeadLetterRetryResult:
    """dead letter 재처리 실행 결과."""

    run_id: int
    status: str
    selected_count: int
    resolved_count: int
    failed_count: int
    blocked_count: int


RetryHandler = Callable[[DeadLetterItem], None]


def retry_unresolved_dead_letters(
    *,
    handlers: Mapping[tuple[str, str], RetryHandler],
    run_metadata: Mapping[str, Any] | None = None,
    include_blocked: bool = False,
    max_attempts: int = 3,
    source_prefix: str | None = None,
    supported_sources: set[tuple[str, str]] | None = None,
) -> DeadLetterRetryResult:
    """unresolved dead letter를 오래된 순서로 재처리한다."""
    metadata = dict(run_metadata or {})
    with get_conn() as conn:
        run_id = start_run(conn, mode="dead_letter_retry", summary=metadata)
        items = load_unresolved_dead_letters(
            conn,
            include_blocked=include_blocked,
            source_prefix=source_prefix,
        )
        conn.commit()

    print(f"[dead-letter-retry] selected={len(items)}", flush=True)
    resolved_count = 0
    failed_count = 0
    blocked_count = 0
    supported = supported_sources or set(handlers)

    for item in items:
        _mark_retrying(item.id, run_id)
        handler = handlers.get((item.source, item.stage))
        if handler is None or (item.source, item.stage) not in supported:
            _record_retry_failure(
                item,
                run_id,
                error=f"no retry handler for {item.source}/{item.stage}",
                max_attempts=max_attempts,
                force_block=True,
            )
            blocked_count += 1
            continue

        try:
            handler(item)
        except Exception as exc:  # noqa: BLE001 - retry boundary records source failures
            blocked = _record_retry_failure(
                item,
                run_id,
                error=str(exc),
                max_attempts=max_attempts,
            )
            if blocked:
                blocked_count += 1
            else:
                failed_count += 1
        else:
            _resolve_retry(item.id)
            resolved_count += 1

    status = _retry_status(
        resolved_count=resolved_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
    )
    summary = {
        **metadata,
        "selected_count": len(items),
        "resolved_count": resolved_count,
        "failed_count": failed_count,
        "blocked_count": blocked_count,
    }
    with get_conn() as conn:
        finish_run(conn, run_id, status=status, summary=summary)
        conn.commit()

    print(
        "[dead-letter-retry] done "
        f"resolved={resolved_count} failed={failed_count} blocked={blocked_count}",
        flush=True,
    )
    return DeadLetterRetryResult(
        run_id=run_id,
        status=status,
        selected_count=len(items),
        resolved_count=resolved_count,
        failed_count=failed_count,
        blocked_count=blocked_count,
    )


def load_unresolved_dead_letters(
    conn: psycopg.Connection,
    *,
    include_blocked: bool = False,
    source_prefix: str | None = None,
) -> tuple[DeadLetterItem, ...]:
    """재처리할 unresolved dead letter를 오래된 순서로 읽는다."""
    statuses = ["pending", "retrying"]
    if include_blocked:
        statuses.append("blocked")

    with conn.cursor() as cur:
        source_filter = ""
        params: list[Any] = [statuses]
        if source_prefix is not None:
            source_filter = "AND source LIKE %s"
            params.append(f"{source_prefix}%")
        cur.execute(
            f"""
            SELECT
                id, run_id, source, stage, item_key, payload, error,
                attempts, status, first_failed_at, last_failed_at
            FROM dead_letters
            WHERE status = ANY(%s)
              {source_filter}
            ORDER BY last_failed_at ASC, id ASC
            """,
            params,
        )
        return tuple(
            DeadLetterItem(
                id=row[0],
                run_id=row[1],
                source=row[2],
                stage=row[3],
                item_key=row[4],
                payload=row[5] or {},
                error=row[6],
                attempts=row[7],
                status=row[8],
                first_failed_at=row[9],
                last_failed_at=row[10],
            )
            for row in cur.fetchall()
        )


def _mark_retrying(dead_letter_id: int, run_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dead_letters
            SET status = 'retrying',
                run_id = %s
            WHERE id = %s
            """,
            (run_id, dead_letter_id),
        )
        conn.commit()


def _resolve_retry(dead_letter_id: int) -> None:
    with get_conn() as conn:
        resolve_dead_letter(conn, dead_letter_id)
        conn.commit()


def _record_retry_failure(
    item: DeadLetterItem,
    run_id: int,
    *,
    error: str,
    max_attempts: int,
    force_block: bool = False,
) -> bool:
    next_attempts = item.attempts + 1
    blocked = force_block or next_attempts >= max_attempts
    with get_conn() as conn:
        record_dead_letter(
            conn,
            run_id=run_id,
            source=item.source,
            stage=item.stage,
            item_key=item.item_key,
            payload=item.payload,
            error=error,
            status="blocked" if blocked else "pending",
        )
        conn.commit()
    return blocked


def _retry_status(*, resolved_count: int, failed_count: int, blocked_count: int) -> str:
    if failed_count == 0 and blocked_count == 0:
        return "success"
    if resolved_count > 0:
        return "degraded_success"
    return "blocked"
