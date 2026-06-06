"""외부 HTTP 동시성 상한 검증."""

from __future__ import annotations

import pytest

from congress_db.core.throttle import cap_worker_count, cap_worker_levels


def test_cap_worker_count_uses_configured_http_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONGRESS_DB_HTTP_CONCURRENCY_LIMIT", "7")

    assert cap_worker_count(20) == 7
    assert cap_worker_count(5) == 5
    assert cap_worker_levels((5, 20, 50, 100, 200)) == (5, 7)


def test_cap_worker_count_rejects_non_positive_requested_workers() -> None:
    with pytest.raises(ValueError):
        cap_worker_count(0)
