"""dead letter 재시도 orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..core.db import get_conn
from .ingest_state import resolve_dead_letter
from .ingest_bills import retry_bill_summary
from .ingest_votes import retry_vote_rows


@dataclass(frozen=True)
class DeadLetter:
    """재시도 대상 실패 item."""

    id: int
    source: str
    stage: str
    item_key: str
    payload: Mapping[str, Any]
    attempts: int


@dataclass(frozen=True)
class DeadLetterRetryResult:
    """dead letter 재시도 결과."""

    unresolved_count: int
    attempted_count: int
    resolved_count: int
    unhandled_count: int
    failed_count: int
    sample_failures: tuple[str, ...]


RetryHandler = Callable[[DeadLetter], bool]


def retry_dead_letters(
    handlers: Mapping[tuple[str, str], RetryHandler] | None = None,
    source_prefix: str | None = None,
) -> DeadLetterRetryResult:
    """unresolved dead letter를 가능한 handler로 재시도한다."""
    selected_handlers = default_retry_handlers() if handlers is None else dict(handlers)
    dead_letters = _load_unresolved_dead_letters(source_prefix=source_prefix)
    attempted_count = 0
    resolved_count = 0
    unhandled_count = 0
    failed_count = 0
    sample_failures: list[str] = []

    for dead_letter in dead_letters:
        handler = selected_handlers.get((dead_letter.source, dead_letter.stage))
        if handler is None:
            unhandled_count += 1
            continue

        attempted_count += 1
        _mark_retrying(dead_letter.id)
        try:
            resolved = handler(dead_letter)
        except Exception as exc:  # pragma: no cover - defensive audit path
            resolved = False
            sample_failures.append(f"{dead_letter.source}:{dead_letter.item_key}: {exc}")

        if resolved:
            _resolve(dead_letter.id)
            resolved_count += 1
        else:
            _mark_retry_failed(dead_letter.id)
            failed_count += 1

    return DeadLetterRetryResult(
        unresolved_count=len(dead_letters),
        attempted_count=attempted_count,
        resolved_count=resolved_count,
        unhandled_count=unhandled_count,
        failed_count=failed_count,
        sample_failures=tuple(sample_failures[:5]),
    )


def default_retry_handlers() -> dict[tuple[str, str], RetryHandler]:
    """현재 자동 재시도가 가능한 dead letter handler 목록."""
    return {
        ("bills.summary", "fetch"): _retry_bill_summary,
        ("votes.rows", "fetch"): _retry_vote_rows,
    }


def _retry_bill_summary(dead_letter: DeadLetter) -> bool:
    bill_no = str(dead_letter.payload.get("bill_no") or dead_letter.item_key)
    return retry_bill_summary(bill_no)


def _retry_vote_rows(dead_letter: DeadLetter) -> bool:
    bill_id = str(dead_letter.payload.get("bill_id") or dead_letter.item_key)
    return retry_vote_rows(bill_id)


def _load_unresolved_dead_letters(*, source_prefix: str | None = None) -> tuple[DeadLetter, ...]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, source, stage, item_key, payload, attempts
            FROM dead_letters
            WHERE status IN ('pending', 'retrying', 'blocked')
              AND (%s::text IS NULL OR source LIKE %s)
            ORDER BY last_failed_at ASC, id ASC
            """,
            (source_prefix, f"{source_prefix}%" if source_prefix is not None else None),
        )
        return tuple(
            DeadLetter(
                id=row[0],
                source=row[1],
                stage=row[2],
                item_key=row[3],
                payload=row[4] or {},
                attempts=row[5],
            )
            for row in cur.fetchall()
        )


def _mark_retrying(dead_letter_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dead_letters
            SET status = 'retrying',
                attempts = attempts + 1,
                last_failed_at = now()
            WHERE id = %s
            """,
            (dead_letter_id,),
        )
        conn.commit()


def _mark_retry_failed(dead_letter_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dead_letters
            SET status = 'pending',
                last_failed_at = now()
            WHERE id = %s
            """,
            (dead_letter_id,),
        )
        conn.commit()


def _resolve(dead_letter_id: int) -> None:
    with get_conn() as conn:
        resolve_dead_letter(conn, dead_letter_id)
        conn.commit()
