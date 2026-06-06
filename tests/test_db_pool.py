"""DB connection pool 경로 검증."""

from __future__ import annotations

from typing import Any

import congress_db.core.db as db


class _ConnectionContext:
    def __init__(self, conn: object):
        self._conn = conn

    def __enter__(self) -> object:
        return self._conn

    def __exit__(self, *args: Any) -> None:
        return None


def test_get_pooled_conn_reuses_single_pool_and_disables_prepared_statements(
    monkeypatch,
) -> None:
    db.close_pool()
    instances: list[object] = []

    class FakePool:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.conn = object()
            self.closed = False
            instances.append(self)

        def connection(self) -> _ConnectionContext:
            return _ConnectionContext(self.conn)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(db, "ConnectionPool", FakePool)
    monkeypatch.setenv("DATABASE_URL", "postgres://direct")
    monkeypatch.setenv("DATABASE_POOL_URL", "postgres://pooled")

    with db.get_pooled_conn() as first:
        assert first is instances[0].conn
    with db.get_pooled_conn() as second:
        assert second is instances[0].conn

    assert len(instances) == 1
    pool = instances[0]
    assert pool.kwargs["conninfo"] == "postgres://pooled"
    assert pool.kwargs["kwargs"]["prepare_threshold"] is None

    db.close_pool()
    assert pool.closed is True
