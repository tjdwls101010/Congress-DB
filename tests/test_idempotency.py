"""Slice 1 RGR 3 — schema.sql 멱등 적용 검증.

`make db-migrate`를 두 번 호출해도 에러 없이 통과하고, 예상 테이블이 그대로
유지되어야 한다. (CREATE TABLE/INDEX IF NOT EXISTS 보장.)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.test_schema import EXPECTED_TABLES, _public_tables

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_db_migrate_can_run_twice() -> None:
    """db-migrate 두 번째 호출도 returncode 0 (에러 없음)."""
    result = subprocess.run(
        ["make", "db-migrate"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"


def test_table_set_unchanged_after_double_migrate() -> None:
    """db-migrate를 한 번 더 호출해도 테이블 집합이 그대로다 (누락/추가 없음)."""
    subprocess.run(
        ["make", "db-migrate"], cwd=REPO_ROOT, capture_output=True, check=True
    )
    assert _public_tables() == EXPECTED_TABLES
