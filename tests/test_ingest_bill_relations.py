"""bill_relations 대안 관계 적재 검증."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.core.db import get_conn
from congress_db.ingest.ingest_bill_relations import (
    _load_bill_relation_targets,
    _parse_selref_bill_id,
    ingest_bill_relations,
)

TEST_ABSORBED_1 = "TEST_REL_ABSORBED_1"
TEST_ABSORBED_2 = "TEST_REL_ABSORBED_2"
TEST_ABSORBED_3 = "TEST_REL_ABSORBED_3"
TEST_ABSORBED_4 = "TEST_REL_ABSORBED_4"
TEST_ABSORBED_C1 = "TEST_REL_ABSORBED_C1"
TEST_ABSORBED_HAS_REL = "TEST_REL_ABSORBED_HAS_REL"
TEST_ALT = "TEST_REL_ALT"
TEST_BILLS = (
    TEST_ABSORBED_1,
    TEST_ABSORBED_2,
    TEST_ABSORBED_3,
    TEST_ABSORBED_4,
    TEST_ABSORBED_C1,
    TEST_ABSORBED_HAS_REL,
    TEST_ALT,
)


@pytest.fixture(autouse=True)
def clean_relation_rows() -> None:
    _delete_relation_rows()
    yield
    _delete_relation_rows()


def _delete_relation_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM bill_relations
            WHERE absorbed_bill_id = ANY(%s)
               OR alternative_bill_id = ANY(%s)
            """,
            (list(TEST_BILLS), list(TEST_BILLS)),
        )
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_BILLS),))
        conn.commit()


def _insert_bill(
    bill_id: str,
    bill_no: str,
    proc_result: str | None = None,
    *,
    cmt_proc_result: str | None = None,
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name, propose_dt, proc_result, cmt_proc_result)
            VALUES (%s, %s, %s, '2999-01-01', %s, %s)
            """,
            (bill_id, bill_no, bill_id, proc_result, cmt_proc_result),
        )
        conn.commit()


def _insert_relation(absorbed_bill_id: str, alternative_bill_id: str, relation_type: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bill_relations (absorbed_bill_id, alternative_bill_id, relation_type)
            VALUES (%s, %s, %s)
            """,
            (absorbed_bill_id, alternative_bill_id, relation_type),
        )
        conn.commit()


def _html(selref: str | None) -> str:
    value_attr = "" if selref is None else f"value='{selref}'"
    return f"<html><body><input type='hidden' id='selRefBillId' {value_attr}></body></html>"


def test_parse_selref_bill_id_reads_hidden_input() -> None:
    assert _parse_selref_bill_id(_html(TEST_ALT)) == TEST_ALT
    assert _parse_selref_bill_id(_html("")) is None
    assert _parse_selref_bill_id("<html></html>") is None


def test_ingest_bill_relations_upserts_relations_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _insert_bill(TEST_ALT, "9900000")
    _insert_bill(TEST_ABSORBED_1, "9900001", "대안반영폐기")
    _insert_bill(TEST_ABSORBED_2, "9900002", "수정안반영폐기")
    calls: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        bill_id = kwargs["params"]["billId"]
        calls.append(bill_id)
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.text = _html(TEST_ALT)
        response.apparent_encoding = "utf-8"
        response.raise_for_status = MagicMock()
        return response

    monkeypatch.setattr("congress_db.ingest.ingest_bill_relations.requests.get", fake_get)

    first = ingest_bill_relations(limit=2, worker_count=1, retry_delays=())
    second = ingest_bill_relations(limit=2, worker_count=1, retry_delays=())

    assert first.target_count == 2
    assert first.relation_count == 2
    assert first.failure_count == 0
    assert first.selected_worker_count == 1
    assert second.relation_count == 2
    assert second.failure_count == 0
    assert calls.count(TEST_ABSORBED_1) == 2
    assert calls.count(TEST_ABSORBED_2) == 2

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT absorbed_bill_id, alternative_bill_id, relation_type
            FROM bill_relations
            WHERE absorbed_bill_id = ANY(%s)
            ORDER BY absorbed_bill_id
            """,
            ([TEST_ABSORBED_1, TEST_ABSORBED_2],),
        )
        rows = cur.fetchall()

    assert rows == [
        (TEST_ABSORBED_1, TEST_ALT, "대안반영"),
        (TEST_ABSORBED_2, TEST_ALT, "수정안반영"),
    ]


def test_ingest_bill_relations_preserves_missing_alt_bill_id_but_fails_missing_selref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _insert_bill(TEST_ABSORBED_3, "9900003", "대안반영폐기")
    _insert_bill(TEST_ABSORBED_4, "9900004", "수정안반영폐기")

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        bill_id = kwargs["params"]["billId"]
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.raise_for_status = MagicMock()
        response.apparent_encoding = "utf-8"
        response.text = _html(None if bill_id == TEST_ABSORBED_3 else "MISSING_ALT")
        return response

    monkeypatch.setattr("congress_db.ingest.ingest_bill_relations.requests.get", fake_get)

    result = ingest_bill_relations(limit=2, worker_count=1, retry_delays=())

    assert result.target_count == 2
    assert result.relation_count == 1
    assert result.failure_count == 1
    assert {
        (failure.bill_id, failure.reason)
        for failure in result.failures
    } == {
        (TEST_ABSORBED_3, "missing_selref"),
    }

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT absorbed_bill_id, alternative_bill_id, relation_type
            FROM bill_relations
            WHERE absorbed_bill_id = ANY(%s)
            """,
            ([TEST_ABSORBED_3, TEST_ABSORBED_4],),
        )
        assert cur.fetchall() == [(TEST_ABSORBED_4, "MISSING_ALT", "수정안반영")]


def test_load_targets_missing_only_excludes_bills_with_existing_relation() -> None:
    _insert_bill(TEST_ALT, "9900000")
    _insert_bill(TEST_ABSORBED_1, "9900001", "대안반영폐기")  # relation 미보유
    _insert_bill(TEST_ABSORBED_HAS_REL, "9900002", "대안반영폐기")  # relation 보유
    _insert_relation(TEST_ABSORBED_HAS_REL, TEST_ALT, "대안반영")

    all_ids = {t.bill_id for t in _load_bill_relation_targets(relation_fetch_mode="all")}
    missing_ids = {t.bill_id for t in _load_bill_relation_targets(relation_fetch_mode="missing")}

    assert {TEST_ABSORBED_1, TEST_ABSORBED_HAS_REL} <= all_ids
    assert TEST_ABSORBED_1 in missing_ids
    assert TEST_ABSORBED_HAS_REL not in missing_ids  # 이미 보유 → 재스크랩 제외


def test_load_targets_includes_committee_terminated_c1_with_derived_relation_type() -> None:
    # C1: proc_result NULL·cmt_proc_result 폐기인 소관위-종료 원안도 선정 대상.
    _insert_bill(
        TEST_ABSORBED_C1,
        "9900010",
        proc_result=None,
        cmt_proc_result="대안반영폐기",
    )
    targets = {t.bill_id: t for t in _load_bill_relation_targets(relation_fetch_mode="all")}

    assert TEST_ABSORBED_C1 in targets
    assert targets[TEST_ABSORBED_C1].relation_type == "대안반영"  # cmt_proc_result에서 파생


def test_load_targets_missing_only_includes_committee_terminated_c1() -> None:
    _insert_bill(
        TEST_ABSORBED_C1,
        "9900010",
        proc_result=None,
        cmt_proc_result="수정안반영폐기",
    )
    missing = {t.bill_id: t for t in _load_bill_relation_targets(relation_fetch_mode="missing")}

    assert TEST_ABSORBED_C1 in missing
    assert missing[TEST_ABSORBED_C1].relation_type == "수정안반영"


def test_bill_lineage_derives_relation_type_from_cmt_for_committee_terminated() -> None:
    # C1 뷰 갱신(036): proc_result가 NULL이어도 cmt_proc_result 폐기면 relation_type이 파생돼
    # 뷰에 노출된다("bill_lineage 0행 ≠ 미흡수" 함정의 뿌리 제거).
    _insert_bill(TEST_ALT, "9900000", "원안가결")
    _insert_bill(TEST_ABSORBED_C1, "9900010", proc_result=None, cmt_proc_result="대안반영폐기")
    _insert_relation(TEST_ABSORBED_C1, TEST_ALT, "대안반영")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT absorbed_proc_result, alternative_bill_no, relation_type
            FROM bill_lineage WHERE absorbed_bill_id = %s
            """,
            (TEST_ABSORBED_C1,),
        )
        row = cur.fetchone()

    assert row == (None, "9900000", "대안반영")
