"""회의록 통합 식별자 파싱."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def extract_mnts_id(value: str | int | None) -> int:
    """PDF URL의 `id` 또는 `CONFER_NUM`을 `meetings.mnts_id` 정수로 바꾼다."""
    if value is None:
        raise ValueError("mnts_id source is missing")
    if isinstance(value, int):
        return value

    source = value.strip()
    if source.isdecimal():
        return int(source)

    query = parse_qs(urlparse(source).query)
    ids = query.get("id")
    if ids and ids[0].isdecimal():
        return int(ids[0])
    raise ValueError(f"cannot extract mnts_id from {value!r}")
