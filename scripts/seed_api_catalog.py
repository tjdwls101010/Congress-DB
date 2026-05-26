#!/usr/bin/env python3
"""api_catalog seed CLI — PRD 확정 10개 endpoint를 UPSERT.

사용법::

    make db-up         # Postgres + 스키마 적용
    uv run python scripts/seed_api_catalog.py

멱등하므로 여러 번 실행해도 안전.
"""

from __future__ import annotations

from congress_db.api_catalog import seed_pipeline_endpoints


def main() -> None:
    n = seed_pipeline_endpoints()
    print(f"Seeded {n} pipeline endpoints into api_catalog.")


if __name__ == "__main__":
    main()
