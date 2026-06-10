"""bill_source_aliases 해소 백필 검증."""

from __future__ import annotations

from congress_db.core.db import get_conn
from congress_db.ingest.bill_source_aliases import (
    _parse_bill_no,
    resolve_bill_source_aliases,
)

TEST_CANONICAL = "TEST_ALIAS_CANONICAL"
TEST_ABSORBED_1 = "TEST_ALIAS_ABSORBED_1"
TEST_ABSORBED_2 = "TEST_ALIAS_ABSORBED_2"
TEST_GAP_ABSORBED = "TEST_ALIAS_GAP_ABSORBED"
TEST_SOURCE_ID = "TEST_ALIAS_SOURCE"
TEST_GAP_SOURCE_ID = "TEST_ALIAS_GAP_SOURCE"
TEST_BILL_IDS = (
    TEST_CANONICAL,
    TEST_ABSORBED_1,
    TEST_ABSORBED_2,
    TEST_GAP_ABSORBED,
)


def setup_function() -> None:
    _delete_test_rows()


def teardown_function() -> None:
    _delete_test_rows()


def _delete_test_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM bill_source_aliases WHERE source_bill_id = ANY(%s)",
            ([TEST_SOURCE_ID, TEST_GAP_SOURCE_ID],),
        )
        cur.execute(
            """
            DELETE FROM bill_relations
            WHERE absorbed_bill_id = ANY(%s)
               OR alternative_bill_id = ANY(%s)
            """,
            (list(TEST_BILL_IDS), [TEST_SOURCE_ID, TEST_GAP_SOURCE_ID]),
        )
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_BILL_IDS),))
        conn.commit()


def _insert_bill(bill_id: str, bill_no: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, propose_dt)
            VALUES (%s, %s, %s, '2999-01-01')
            """,
            (bill_id, bill_no, bill_id),
        )
        conn.commit()


def _insert_relation(absorbed_bill_id: str, source_bill_id: str, relation_type: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bill_relations (
                absorbed_bill_id, alternative_bill_id, relation_type
            )
            VALUES (%s, %s, %s)
            """,
            (absorbed_bill_id, source_bill_id, relation_type),
        )
        conn.commit()


def _bill_no_html(bill_no: str | None) -> str:
    if bill_no is None:
        return "<html><body></body></html>"
    return f"<html><body><input id='billNo' name='billNo' value='{bill_no}'></body></html>"


def test_parse_bill_no_reads_likms_bill_no_input() -> None:
    assert _parse_bill_no(_bill_no_html("2212725")) == "2212725"
    assert _parse_bill_no("<html></html>") is None
    assert _parse_bill_no("<input id='billNo' value=''>") is None


def test_resolve_bill_source_aliases_maps_source_id_to_canonical_bill(
    monkeypatch,
) -> None:
    _insert_bill(TEST_CANONICAL, "2992725")
    _insert_bill(TEST_ABSORBED_1, "2990001")
    _insert_bill(TEST_ABSORBED_2, "2990002")
    _insert_relation(TEST_ABSORBED_1, TEST_SOURCE_ID, "대안반영")
    _insert_relation(TEST_ABSORBED_2, TEST_SOURCE_ID, "대안반영")
    monkeypatch.setattr(
        "congress_db.ingest.bill_source_aliases._fetch_likms_bill_detail",
        lambda source_bill_id: _bill_no_html("2992725"),
    )

    result = resolve_bill_source_aliases(
        source_bill_ids=(TEST_SOURCE_ID,),
        retry_delays=(),
    )

    assert result.target_count == 1
    assert result.alias_count == 1
    assert result.alias_relation_count == 2
    assert result.accepted_gap_count == 0
    assert result.ambiguous_count == 0

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source, source_bill_id, bill_no, canonical_bill_id
            FROM bill_source_aliases
            WHERE source_bill_id = %s
            """,
            (TEST_SOURCE_ID,),
        )
        alias = cur.fetchone()
        cur.execute(
            """
            SELECT count(*) AS still_unreachable
            FROM bill_relations r
            LEFT JOIN bills b ON b.bill_id = r.alternative_bill_id
            LEFT JOIN bill_source_aliases a ON a.source_bill_id = r.alternative_bill_id
            LEFT JOIN bills cb ON cb.bill_id = a.canonical_bill_id
            WHERE r.relation_type = '대안반영'
              AND r.alternative_bill_id = %s
              AND b.bill_id IS NULL
              AND cb.bill_id IS NULL
            """,
            (TEST_SOURCE_ID,),
        )
        still_unreachable = cur.fetchone()[0]

    assert alias == (
        "likms_billdetail",
        TEST_SOURCE_ID,
        "2992725",
        TEST_CANONICAL,
    )
    assert still_unreachable == 0


def test_resolve_bill_source_aliases_records_missing_bill_no_as_accepted_gap(
    monkeypatch,
) -> None:
    _insert_bill(TEST_GAP_ABSORBED, "2990003")
    _insert_relation(TEST_GAP_ABSORBED, TEST_GAP_SOURCE_ID, "수정안반영")
    monkeypatch.setattr(
        "congress_db.ingest.bill_source_aliases._fetch_likms_bill_detail",
        lambda source_bill_id: _bill_no_html(None),
    )

    result = resolve_bill_source_aliases(
        source_bill_ids=(TEST_GAP_SOURCE_ID,),
        retry_delays=(),
    )

    assert result.target_count == 1
    assert result.alias_count == 0
    assert result.accepted_gap_count == 1
    assert result.accepted_gap_relation_count == 1
    assert result.accepted_gaps[0].reason == "missing_bill_no"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM bill_source_aliases WHERE source_bill_id = %s",
            (TEST_GAP_SOURCE_ID,),
        )
        alias_count = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM bills WHERE bill_id = %s",
            (TEST_GAP_SOURCE_ID,),
        )
        synthetic_bill_count = cur.fetchone()[0]

    assert alias_count == 0
    assert synthetic_bill_count == 0


def test_resolve_bill_source_aliases_is_idempotent(monkeypatch) -> None:
    _insert_bill(TEST_CANONICAL, "2992725")
    _insert_bill(TEST_ABSORBED_1, "2990001")
    _insert_relation(TEST_ABSORBED_1, TEST_SOURCE_ID, "대안반영")
    monkeypatch.setattr(
        "congress_db.ingest.bill_source_aliases._fetch_likms_bill_detail",
        lambda source_bill_id: _bill_no_html("2992725"),
    )

    first = resolve_bill_source_aliases(
        source_bill_ids=(TEST_SOURCE_ID,),
        retry_delays=(),
    )
    second = resolve_bill_source_aliases(
        source_bill_ids=(TEST_SOURCE_ID,),
        retry_delays=(),
    )

    assert first.alias_count == 1
    assert second.alias_count == 1

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM bill_source_aliases WHERE source_bill_id = %s",
            (TEST_SOURCE_ID,),
        )
        alias_count = cur.fetchone()[0]

    assert alias_count == 1
