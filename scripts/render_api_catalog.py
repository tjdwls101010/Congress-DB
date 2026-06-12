#!/usr/bin/env python3
"""docs/ops/API-CATALOG.md 자동 생성 CLI.

사용법::

    make render-catalog    # docs/ops/API-CATALOG.md 생성
"""

from __future__ import annotations

from pathlib import Path

from congress_db.ops.api_catalog_render import pipeline_catalog_rows, render_pipeline_catalog_md

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "docs" / "ops" / "API-CATALOG.md"


def main() -> None:
    rows = pipeline_catalog_rows()
    md = render_pipeline_catalog_md(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(md, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(rows)} endpoints)")


if __name__ == "__main__":
    main()
