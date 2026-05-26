"""Slice 2 RGR 2 — api_catalog seed + verification result 갱신 검증.

각 테스트 시작 시 api_catalog를 TRUNCATE해서 다른 테스트와 격리.
"""

from __future__ import annotations

import pytest

from congress_db.api_catalog import (
    fetch_pipeline_catalog_rows,
    seed_pipeline_endpoints,
    update_verification_result,
)
from congress_db.db import get_conn
from congress_db.endpoints import PIPELINE_ENDPOINTS


@pytest.fixture(autouse=True)
def clean_api_catalog() -> None:
    """매 테스트 시작 전 api_catalog 비움."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE api_catalog")
        conn.commit()


def _count_pipeline_rows() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM api_catalog WHERE used_in_pipeline = TRUE"
        )
        result = cur.fetchone()
        return int(result[0]) if result else 0


def test_seed_inserts_all_pipeline_endpoints() -> None:
    n = seed_pipeline_endpoints()

    assert n == len(PIPELINE_ENDPOINTS) == 11
    assert _count_pipeline_rows() == 11


def test_seed_is_idempotent() -> None:
    seed_pipeline_endpoints()
    seed_pipeline_endpoints()

    assert _count_pipeline_rows() == 11


def test_seed_preserves_usage_note_per_spec() -> None:
    seed_pipeline_endpoints()
    rows = {r["inf_id"]: r for r in fetch_pipeline_catalog_rows()}

    for spec in PIPELINE_ENDPOINTS:
        assert spec.inf_id in rows
        assert rows[spec.inf_id]["endpoint"] == spec.endpoint
        assert rows[spec.inf_id]["usage_note"] == spec.usage_note
        assert rows[spec.inf_id]["used_in_pipeline"] is True


def test_update_verification_result_records_status() -> None:
    seed_pipeline_endpoints()
    spec = PIPELINE_ENDPOINTS[0]

    ok = update_verification_result(
        spec.inf_id,
        status="ok",
        has_22nd_data=True,
        total_count_22nd=286,
    )

    assert ok is True
    rows = {r["inf_id"]: r for r in fetch_pipeline_catalog_rows()}
    assert rows[spec.inf_id]["status"] == "ok"
    assert rows[spec.inf_id]["has_22nd_data"] is True
    assert rows[spec.inf_id]["total_count_22nd"] == 286
    assert rows[spec.inf_id]["tested_at"] is not None


def test_update_verification_result_returns_false_for_unknown_inf_id() -> None:
    seed_pipeline_endpoints()

    ok = update_verification_result(
        "NONEXISTENT_INF_ID",
        status="ok",
        has_22nd_data=True,
        total_count_22nd=0,
    )

    assert ok is False


def test_fetch_pipeline_catalog_rows_returns_only_pipeline_endpoints() -> None:
    """used_in_pipeline=FALSE인 row는 fetch_pipeline_catalog_rows에서 제외."""
    seed_pipeline_endpoints()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO api_catalog (inf_id, name, endpoint, used_in_pipeline) "
            "VALUES ('UNUSED_API', '미사용 API', 'unused_endpoint', FALSE)"
        )
        conn.commit()

    rows = fetch_pipeline_catalog_rows()

    inf_ids = {r["inf_id"] for r in rows}
    assert "UNUSED_API" not in inf_ids
    assert len(rows) == 11
