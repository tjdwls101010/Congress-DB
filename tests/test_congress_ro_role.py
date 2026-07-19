"""congress_ro role script keeps the skill surface allowlisted."""

from __future__ import annotations

from pathlib import Path


ROLE_SQL = Path("db/roles/congress_ro.sql")


def _role_sql() -> str:
    return ROLE_SQL.read_text(encoding="utf-8")


def test_congress_ro_role_uses_explicit_allowlist() -> None:
    sql = _role_sql()

    assert "GRANT SELECT ON ALL TABLES" not in sql
    assert "GRANT EXECUTE ON ALL FUNCTIONS" not in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT" not in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE" not in sql

    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM congress_ro" in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM congress_ro" in sql


def test_congress_ro_role_exposes_only_consumer_relations() -> None:
    sql = _role_sql()

    for relation in (
        "members",
        "committees",
        "bills",
        "bill_lead_proposers",
        "bill_coproposers",
        "votes",
        "bill_final_outcomes",
        "bill_lineage",
        "data_freshness",
    ):
        assert relation in sql

    # bill_relations·bill_source_aliases는 ops-internal로 REVOKE (#125): 소비자는 bill_lineage 뷰로 읽음.
    assert "bill_relations," not in sql
    assert "bill_source_aliases," not in sql
    assert "ingest_runs," not in sql
    assert "ingest_cursors," not in sql
    assert "dead_letters," not in sql


def test_congress_ro_role_grants_only_search_functions() -> None:
    sql = _role_sql()

    assert "GRANT EXECUTE ON FUNCTION search_snippet(text, text, integer)" in sql
    assert "GRANT EXECUTE ON FUNCTION search_bills(text, integer)" in sql
