"""api_catalog → Markdown 변환 모듈.

deep module: 호출자는 `render_pipeline_catalog_md(rows)`만 알면 사람이 읽기 좋은
MD 문자열을 받는다. 컬럼 escape, 비어 있는 값 처리, status 별 표시 등 디테일은
내부에 흡수.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def render_pipeline_catalog_md(rows: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    """`api_catalog`의 used_in_pipeline=TRUE row들을 Markdown 표로 변환.

    Args:
        rows: `fetch_pipeline_catalog_rows()`의 결과 형식.
        now: 생성 시각 (테스트 시 주입 가능; 기본은 호출 시각).
    """
    when = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

    lines: list[str] = [
        "# API Catalog",
        "",
        "PRD 확정 OpenAPI의 작동 검증 결과. 1회성 — 자동 재검증 없음.",
        "범위 결정 배경은 [DECISIONS](../design/DECISIONS.md) 참고.",
        "",
        f"_Generated: {when}_",
        "",
        "| endpoint | 이름 | 22대 데이터 | 22대 row 수 | status | usage |",
        "|---|---|---|---|---|---|",
    ]

    if not rows:
        lines.extend(
            [
                "",
                "## Status",
                "",
                "api_catalog 비어 있음 — 재시드 필요. `make seed-catalog` 후 다시 렌더링해야 한다.",
            ]
        )
        return "\n".join(lines) + "\n"

    for r in rows:
        endpoint = r.get("endpoint") or ""
        name = r.get("name") or ""
        has_data = "✓" if r.get("has_22nd_data") else "—"
        count_val = r.get("total_count_22nd")
        count = f"{count_val:,}" if isinstance(count_val, int) else "—"
        status = r.get("status") or "미검증"
        usage = (r.get("usage_note") or "").replace("|", "\\|")
        lines.append(f"| `{endpoint}` | {name} | {has_data} | {count} | {status} | {usage} |")

    notes = [r for r in rows if r.get("skip_reason")]
    if notes:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for r in notes:
            lines.append(f"- `{r.get('endpoint')}`: {r.get('skip_reason')}")

    return "\n".join(lines) + "\n"
