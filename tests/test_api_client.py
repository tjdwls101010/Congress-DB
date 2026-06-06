"""Slice 2 RGR 1 — congress_db.core.api_client wrapper 단위 테스트.

requests.get은 monkeypatch로 모킹. 실제 277개 API 호출은 별도 manual 스크립트.

테스트 대상 행동:
1. 정상 응답을 ApiResponse(status="ok")로 파싱
2. list_total_count=0을 status="no_data"로 인식
3. HTTP 에러는 status="error"
4. fetch_with_age_attempts는 4가지 대수 파라미터를 순차 시도, 첫 ok 채택
5. fetch_with_age_attempts는 어떤 대수 파라미터가 채택됐는지 기록
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.core.api_client import (
    AGE_PARAM_ATTEMPTS,
    ApiResponse,
    fetch_endpoint,
    fetch_endpoint_with_retry,
    fetch_with_age_attempts,
)


def _ok_envelope(endpoint: str, total: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """국회 OpenAPI의 정상 응답 형식 (legacy fetch_bills.py에서 추출)."""
    return {
        endpoint: [
            {"head": [{"list_total_count": total}, {"RESULT": {"CODE": "INFO-000"}}]},
            {"row": rows},
        ]
    }


def _no_data_response() -> dict[str, Any]:
    return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}


def _mock_get_factory(json_payload: Any, *, status_code: int = 200, raise_exc: Exception | None = None):
    """requests.get을 대체할 가짜 함수 생성."""

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        if raise_exc is not None:
            raise raise_exc
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_payload
        response.raise_for_status = MagicMock()
        if status_code >= 400:
            import requests
            response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
        return response

    return _fake_get


def _sequence_get_factory(payloads: Iterable[Any]):
    """호출마다 다른 응답을 반환하는 가짜."""
    iterator = iter(payloads)

    def _fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        payload = next(iterator)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = payload
        response.raise_for_status = MagicMock()
        return response

    return _fake_get


# -------------------------------------------------------------------------
# fetch_endpoint
# -------------------------------------------------------------------------

def test_fetch_endpoint_parses_ok_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _ok_envelope("foo", total=3, rows=[{"a": 1}, {"a": 2}, {"a": 3}])
    monkeypatch.setattr("congress_db.core.api_client.requests.get", _mock_get_factory(payload))

    resp = fetch_endpoint("foo", {"AGE": "22"}, api_key="testkey")

    assert resp.status == "ok"
    assert resp.total_count == 3
    assert resp.rows == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert resp.error is None


def test_fetch_endpoint_returns_no_data_when_total_count_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _ok_envelope("foo", total=0, rows=[])
    monkeypatch.setattr("congress_db.core.api_client.requests.get", _mock_get_factory(payload))

    resp = fetch_endpoint("foo", api_key="testkey")

    assert resp.status == "no_data"
    assert resp.total_count == 0


def test_fetch_endpoint_returns_no_data_on_result_info_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """RESULT-only 응답(INFO-200)도 no_data로 처리."""
    monkeypatch.setattr(
        "congress_db.core.api_client.requests.get", _mock_get_factory(_no_data_response())
    )

    resp = fetch_endpoint("foo", api_key="testkey")

    assert resp.status == "no_data"


def test_fetch_endpoint_returns_error_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests
    monkeypatch.setattr(
        "congress_db.core.api_client.requests.get",
        _mock_get_factory(None, raise_exc=requests.ConnectionError("boom")),
    )

    resp = fetch_endpoint("foo", api_key="testkey")

    assert resp.status == "error"
    assert resp.error is not None and "boom" in resp.error


def test_fetch_endpoint_with_retry_recovers_transient_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    calls = 0

    def fake_get(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise requests.Timeout("Read timed out")
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _ok_envelope("foo", total=1, rows=[{"x": 1}])
        response.raise_for_status = MagicMock()
        return response

    monkeypatch.setattr("congress_db.core.api_client.requests.get", fake_get)
    monkeypatch.setattr("congress_db.core.api_client.time.sleep", lambda delay: None)

    resp = fetch_endpoint_with_retry("foo", api_key="testkey", retry_delays=(0,))

    assert resp.status == "ok"
    assert resp.rows == [{"x": 1}]
    assert resp.retry_count == 1
    assert calls == 2


# -------------------------------------------------------------------------
# fetch_with_age_attempts
# -------------------------------------------------------------------------

def test_age_attempts_picks_first_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """첫 시도(DAE_NUM)가 no_data, 두 번째(AGE)가 ok면 AGE 채택."""
    payloads = [
        _ok_envelope("foo", total=0, rows=[]),
        _ok_envelope("foo", total=5, rows=[{"x": 1}]),
        # 이후 시도는 호출되지 않아야 함
    ]
    monkeypatch.setattr(
        "congress_db.core.api_client.requests.get", _sequence_get_factory(payloads)
    )

    resp = fetch_with_age_attempts("foo", {}, api_key="testkey", sleep_between=0)

    assert resp.status == "ok"
    assert resp.total_count == 5
    assert resp.age_param_used == {"AGE": "22"}


def test_age_attempts_returns_last_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """4가지 시도 모두 no_data면 마지막 응답을 반환."""
    payloads = [_ok_envelope("foo", total=0, rows=[]) for _ in AGE_PARAM_ATTEMPTS]
    monkeypatch.setattr(
        "congress_db.core.api_client.requests.get", _sequence_get_factory(payloads)
    )

    resp = fetch_with_age_attempts("foo", {}, api_key="testkey", sleep_between=0)

    assert resp.status == "no_data"


def test_age_attempts_no_age_param_is_attempted(monkeypatch: pytest.MonkeyPatch) -> None:
    """대수 파라미터 없는 시도(빈 dict)도 시퀀스에 포함되어 있다."""
    assert {} in AGE_PARAM_ATTEMPTS
