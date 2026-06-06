"""Slice 1 — DB 셋업 검증 통합 테스트.

이 테스트는 docker-compose의 Postgres가 띄워져 있다는 전제 하에 동작한다.
`make db-up`으로 컨테이너를 먼저 기동할 것.
"""

from congress_db.core.db import get_conn


def test_get_conn_can_execute_select_one() -> None:
    """psycopg로 DB 연결 후 SELECT 1이 1을 반환한다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            assert row == (1,)
