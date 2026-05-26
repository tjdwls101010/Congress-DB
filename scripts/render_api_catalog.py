#!/usr/bin/env python3
"""docs/API-CATALOG.md 자동 생성 CLI.

사용법::

    make seed-catalog
    make verify-catalog    # status / has_22nd_data / total_count_22nd 채움
    make render-catalog    # docs/API-CATALOG.md 생성
"""

from __future__ import annotations

from pathlib import Path

from congress_db.api_catalog import fetch_pipeline_catalog_rows
from congress_db.api_catalog_render import render_pipeline_catalog_md

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "docs" / "API-CATALOG.md"


def main() -> None:
    rows = fetch_pipeline_catalog_rows()
    md = render_pipeline_catalog_md(rows)
    OUTPUT.write_text(md, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(rows)} endpoints)")


if __name__ == "__main__":
    main()
