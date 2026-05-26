"""api_catalog 테이블 적재 / 갱신 유틸리티.

deep module: 호출자는 `seed_pipeline_endpoints()`와 `update_verification_result()`
두 함수만 알면 된다. SQL과 ON CONFLICT 분기는 내부에 흡수.

PRD 확정 10개 endpoint만 다룬다 — ADR-0001 참고.
"""

from __future__ import annotations

from typing import Any

from .db import get_conn
from .endpoints import PIPELINE_ENDPOINTS


_SEED_SQL = """
    INSERT INTO api_catalog (inf_id, name, endpoint, used_in_pipeline, usage_note)
    VALUES (%(inf_id)s, %(name)s, %(endpoint)s, TRUE, %(usage_note)s)
    ON CONFLICT (inf_id) DO UPDATE SET
        name             = EXCLUDED.name,
        endpoint         = EXCLUDED.endpoint,
        used_in_pipeline = TRUE,
        usage_note       = EXCLUDED.usage_note
"""


def seed_pipeline_endpoints() -> int:
    """`PIPELINE_ENDPOINTS` 10개를 api_catalog에 UPSERT.

    멱등. 호출자는 결과 row 수만 알면 됨.
    """
    with get_conn() as conn, conn.cursor() as cur:
        for spec in PIPELINE_ENDPOINTS:
            cur.execute(
                _SEED_SQL,
                {
                    "inf_id": spec.inf_id,
                    "name": spec.name,
                    "endpoint": spec.endpoint,
                    "usage_note": spec.usage_note,
                },
            )
        conn.commit()
    return len(PIPELINE_ENDPOINTS)


_UPDATE_SQL = """
    UPDATE api_catalog
    SET tested_at        = now(),
        status           = %(status)s,
        has_22nd_data    = %(has_22nd_data)s,
        total_count_22nd = %(total_count_22nd)s,
        skip_reason      = %(skip_reason)s
    WHERE inf_id = %(inf_id)s
"""


def update_verification_result(
    inf_id: str,
    *,
    status: str,
    has_22nd_data: bool | None,
    total_count_22nd: int | None,
    skip_reason: str | None = None,
) -> bool:
    """단일 endpoint의 검증 결과를 api_catalog에 기록.

    Returns: 업데이트된 row가 있으면 True (= 해당 inf_id가 미리 seed돼 있을 때).
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            _UPDATE_SQL,
            {
                "inf_id": inf_id,
                "status": status,
                "has_22nd_data": has_22nd_data,
                "total_count_22nd": total_count_22nd,
                "skip_reason": skip_reason,
            },
        )
        updated = cur.rowcount
        conn.commit()
    return updated > 0


def fetch_pipeline_catalog_rows() -> list[dict[str, Any]]:
    """`used_in_pipeline=TRUE`인 api_catalog row들을 dict 리스트로 반환.

    Markdown 렌더링 등 read-only 호출자가 사용.
    """
    sql = """
        SELECT inf_id, name, endpoint, used_in_pipeline, usage_note,
               status, has_22nd_data, total_count_22nd, tested_at, skip_reason
        FROM api_catalog
        WHERE used_in_pipeline = TRUE
        ORDER BY endpoint
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        columns = [d.name for d in cur.description] if cur.description else []
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
