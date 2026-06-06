#!/usr/bin/env python3
"""docs/ops/API-CATALOG.md 자동 생성 CLI.

사용법::

    make seed-catalog
    make verify-catalog    # status / has_22nd_data / total_count_22nd 채움
    make render-catalog    # docs/ops/API-CATALOG.md 생성
"""

from __future__ import annotations

from pathlib import Path

from congress_db.api_catalog import fetch_pipeline_catalog_rows, seed_pipeline_endpoints
from congress_db.api_catalog_render import render_pipeline_catalog_md

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "docs" / "ops" / "API-CATALOG.md"


def main() -> None:
    seed_pipeline_endpoints()
    rows = fetch_pipeline_catalog_rows()
    md = render_pipeline_catalog_md(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(md, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(rows)} endpoints)")


if __name__ == "__main__":
    main()
