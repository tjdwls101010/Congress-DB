"""국회 OpenAPI 호출 wrapper.

deep module 의도: HTTP 요청, JSON 파싱, 응답 envelope 해석, 대수 파라미터 자동
시도를 모두 한 인터페이스 뒤에 흡수한다. 호출자(스크립트, 향후 적재 파이프라인)는
`fetch_endpoint(endpoint, params)` 또는 `fetch_with_age_attempts(...)` 두 함수만
알면 된다.

응답 형식 (legacy fetch_bills.py 분석 결과)::

    {
        "<endpoint>": [
            {"head": [{"list_total_count": N}, {"RESULT": {"CODE": "INFO-000"}}]},
            {"row": [...]}
        ]
    }

또는 데이터 없음/에러 시::

    {"RESULT": {"CODE": "INFO-200", "MESSAGE": "..."}}

`fetch_endpoint`는 이 두 모양을 모두 정규화해서 `ApiResponse`로 돌려준다.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://open.assembly.go.kr/portal/openapi"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 대수 파라미터 자동 시도. 우선순위 순서대로 시도한다.
# 빈 dict는 "대수 파라미터 없이 호출"을 의미 — 일부 API는 대수 개념 자체가 없음.
AGE_PARAM_ATTEMPTS: tuple[dict[str, str], ...] = (
    {"DAE_NUM": "22"},
    {"AGE": "22"},
    {"ERACO": "제22대"},
    {},
)

Status = Literal["ok", "no_data", "error"]


@dataclass(frozen=True)
class ApiResponse:
    """국회 OpenAPI 호출 1회의 정규화된 결과."""

    status: Status
    total_count: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # fetch_with_age_attempts에서 채택된 대수 파라미터. None이면 미적용/무관.
    age_param_used: dict[str, str] | None = None


# -------------------------------------------------------------------------
# 단일 호출
# -------------------------------------------------------------------------

def fetch_endpoint(
    endpoint: str,
    params: dict[str, str] | None = None,
    *,
    api_key: str | None = None,
    p_index: int = 1,
    p_size: int = 100,
    timeout: int = 30,
) -> ApiResponse:
    """단일 endpoint를 한 번 호출한다.

    HTTP/JSON/응답 envelope의 모든 실패 모드는 `ApiResponse.status='error'`로
    정규화된다. 예외는 raise하지 않는다 — 277개 검증 잡을 견고하게 돌리기 위함.
    """
    key = api_key if api_key is not None else os.environ.get("NATIONAL_ASSEMBLY_API_KEY", "")
    query: dict[str, str] = {
        "Key": key,
        "Type": "json",
        "pIndex": str(p_index),
        "pSize": str(p_size),
    }
    if params:
        query.update(params)

    url = f"{BASE_URL}/{endpoint}"
    try:
        r = requests.get(
            url,
            params=query,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        return ApiResponse(status="error", total_count=0, error=str(exc))
    except ValueError as exc:  # json parse
        return ApiResponse(status="error", total_count=0, error=f"JSON parse: {exc}")

    return _parse_response(data)


def _parse_response(data: Any) -> ApiResponse:
    """국회 OpenAPI 응답을 ApiResponse로 정규화."""
    if not isinstance(data, dict):
        return ApiResponse(status="error", total_count=0, error="Unexpected response type")

    # case 1: RESULT-only 응답 (데이터 없음 or 에러)
    if set(data.keys()) == {"RESULT"}:
        result = data["RESULT"]
        code = str(result.get("CODE", ""))
        msg = str(result.get("MESSAGE", ""))
        if "INFO-200" in code or "데이터" in msg:
            return ApiResponse(status="no_data", total_count=0)
        return ApiResponse(status="error", total_count=0, error=f"{code}: {msg}")

    # case 2: endpoint key 응답 (head + row)
    for value in data.values():
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and ("head" in value[0] or "row" in value[0])
        ):
            return _parse_envelope(value)

    return ApiResponse(status="error", total_count=0, error="Unknown response shape")


def _parse_envelope(envelope: list[dict[str, Any]]) -> ApiResponse:
    total_count = 0
    rows: list[dict[str, Any]] = []
    for item in envelope:
        if "head" in item and item["head"]:
            head = item["head"]
            total_count = int(head[0].get("list_total_count", 0))
        if "row" in item:
            rows = list(item["row"])
    if total_count == 0:
        return ApiResponse(status="no_data", total_count=0)
    return ApiResponse(status="ok", total_count=total_count, rows=rows)


# -------------------------------------------------------------------------
# 대수 파라미터 자동 시도
# -------------------------------------------------------------------------

def fetch_with_age_attempts(
    endpoint: str,
    params: dict[str, str] | None = None,
    *,
    api_key: str | None = None,
    p_index: int = 1,
    p_size: int = 100,
    timeout: int = 30,
    sleep_between: float = 0.1,
) -> ApiResponse:
    """4가지 대수 파라미터를 순차 시도, 첫 ok 응답을 채택한다.

    모두 실패하면 마지막 응답을 그대로 반환 (status는 no_data 또는 error 그대로).
    """
    base = dict(params or {})
    last: ApiResponse | None = None
    for age_params in AGE_PARAM_ATTEMPTS:
        attempt = {**base, **age_params}
        response = fetch_endpoint(
            endpoint,
            attempt,
            api_key=api_key,
            p_index=p_index,
            p_size=p_size,
            timeout=timeout,
        )
        if response.status == "ok":
            return ApiResponse(
                status=response.status,
                total_count=response.total_count,
                rows=response.rows,
                error=response.error,
                age_param_used=dict(age_params) if age_params else None,
            )
        last = response
        if sleep_between:
            time.sleep(sleep_between)
    assert last is not None  # AGE_PARAM_ATTEMPTS는 비어 있지 않음
    return last
