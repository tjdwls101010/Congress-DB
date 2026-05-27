"""수집 실행 상태 기록.

deep module: 호출자는 run/cursor/dead letter lifecycle 함수만 알면 된다. 상태값
제약, partial unique upsert, timestamp 갱신은 Postgres schema와 이 Module 안에
숨긴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def start_run(
    conn: psycopg.Connection,
    *,
    mode: str,
    overlap_days: int | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    summary: Mapping[str, Any] | None = None,
) -> int:
    """새 ingest run을 `running` 상태로 시작하고 id를 반환한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_runs (
                mode, status, overlap_days, window_start, window_end, summary
            )
            VALUES (%s, 'running', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                mode,
                overlap_days,
                window_start,
                window_end,
                Jsonb(dict(summary or {})),
            ),
        )
        row = cur.fetchone()
    return int(row[0])


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    *,
    status: str,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> bool:
    """ingest run을 종료 상태로 바꾼다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingest_runs
            SET status = %s,
                finished_at = now(),
                summary = COALESCE(%s, summary),
                error = %s
            WHERE id = %s
            RETURNING id
            """,
            (
                status,
                Jsonb(dict(summary)) if summary is not None else None,
                error,
                run_id,
            ),
        )
        return cur.fetchone() is not None


def update_run_summary(
    conn: psycopg.Connection,
    run_id: int,
    summary: Mapping[str, Any],
) -> bool:
    """실행 중인 run의 summary를 갱신한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingest_runs
            SET summary = %s
            WHERE id = %s
            RETURNING id
            """,
            (Jsonb(dict(summary)), run_id),
        )
        return cur.fetchone() is not None


def upsert_cursor(
    conn: psycopg.Connection,
    *,
    source: str,
    cursor_kind: str,
    cursor_value: datetime | None,
    updated_run_id: int,
    overlap_days: int = 30,
) -> None:
    """source별 cursor를 갱신한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_cursors (
                source, cursor_kind, cursor_value, overlap_days, updated_run_id
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source) DO UPDATE SET
                cursor_kind = EXCLUDED.cursor_kind,
                cursor_value = EXCLUDED.cursor_value,
                overlap_days = EXCLUDED.overlap_days,
                updated_run_id = EXCLUDED.updated_run_id,
                updated_at = now()
            """,
            (source, cursor_kind, cursor_value, overlap_days, updated_run_id),
        )


def record_dead_letter(
    conn: psycopg.Connection,
    *,
    run_id: int,
    source: str,
    stage: str,
    item_key: str,
    error: str,
    payload: Mapping[str, Any] | None = None,
    status: str = "pending",
) -> int:
    """실패 item을 기록하고 unresolved 중복은 같은 row의 attempts로 누적한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dead_letters (
                run_id, source, stage, item_key, payload, error, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, stage, item_key)
                WHERE status IN ('pending', 'retrying', 'blocked')
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                payload = EXCLUDED.payload,
                error = EXCLUDED.error,
                attempts = dead_letters.attempts + 1,
                status = EXCLUDED.status,
                last_failed_at = now(),
                resolved_at = NULL
            RETURNING id
            """,
            (
                run_id,
                source,
                stage,
                item_key,
                Jsonb(dict(payload or {})),
                error,
                status,
            ),
        )
        row = cur.fetchone()
    return int(row[0])


def resolve_dead_letter(conn: psycopg.Connection, dead_letter_id: int) -> bool:
    """dead letter를 삭제하지 않고 resolved 상태로 전환한다."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dead_letters
            SET status = 'resolved',
                resolved_at = now()
            WHERE id = %s
            RETURNING id
            """,
            (dead_letter_id,),
        )
        return cur.fetchone() is not None
