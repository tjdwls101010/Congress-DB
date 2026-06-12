"""PIPELINE_ENDPOINTS → Markdown 변환 모듈.

deep module: 호출자는 `pipeline_catalog_rows()`와 `render_pipeline_catalog_md(rows)`만
알면 사람이 읽기 좋은 MD 문자열을 받는다. 컬럼 escape와 비어 있는 값 처리 디테일은
내부에 흡수.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from congress_db.core.endpoints import PIPELINE_ENDPOINTS


def pipeline_catalog_rows() -> list[dict[str, Any]]:
    """PIPELINE_ENDPOINTS 상수를 문서 렌더링용 row로 변환한다."""
    return [
        {
            "inf_id": spec.inf_id,
            "name": spec.name,
            "endpoint": spec.endpoint,
            "used_in_pipeline": True,
            "usage_note": spec.usage_note,
            "status": "not-applicable",
            "has_22nd_data": None,
            "total_count_22nd": None,
            "skip_reason": None,
        }
        for spec in sorted(PIPELINE_ENDPOINTS, key=lambda item: item.endpoint)
    ]


def render_pipeline_catalog_md(rows: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    """PRD 확정 OpenAPI row들을 Markdown 표로 변환.

    Args:
        rows: `pipeline_catalog_rows()`의 결과 형식.
        now: 생성 시각 (테스트 시 주입 가능; 기본은 호출 시각).
    """
    when = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

    lines: list[str] = [
        "# API Catalog",
        "",
        "PRD 확정 OpenAPI 목록. `congress_db/core/endpoints.py`의 `PIPELINE_ENDPOINTS`에서 생성된다.",
        "테이블 미러와 1회성 검증 컬럼은 제거되어 status/row 수는 적용 대상이 아니다.",
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
                "PIPELINE_ENDPOINTS가 비어 있다. 사용 중인 OpenAPI가 없거나 상수 정의를 확인해야 한다.",
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
