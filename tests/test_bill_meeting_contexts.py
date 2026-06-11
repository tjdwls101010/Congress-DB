"""bill_meeting_contexts 뷰 — 회의 fanout evidence 가드레일 (#91).

회의↔법안 연결은 회의 단위라 한 회의에 수십~수백 법안이 걸린다(max 756). "같은 회의에서
다뤄짐"을 특정 법안의 발언 증거로 단정하면 스킬이 과잉주장한다. 이 뷰는 회의의 fanout
(linked_bill_count)과 evidence_scope='meeting_level'을 소비 표면에 노출해, 소비자가 증거
강도를 스스로 판단하게 한다. 버킷 라벨(specific/crowded)은 의도적으로 만들지 않는다 —
연속 분포라 경계가 임의값이고, raw count를 보면 소비자가 판단한다(DECISIONS 2026-06-11).

테스트는 로컬 docker DB에 sentinel fixture를 넣어 뷰의 *집계 로직*을 결정론적으로 검증한다
(실데이터·백필 상태 무관). 실데이터 shape 검증은 Neon smoke가 따로 한다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from congress_db.core.db import get_conn

TEST_MEETING_ID = 990_000_001
TEST_BILL_IDS = ("TEST_BMC_B1", "TEST_BMC_B2", "TEST_BMC_B3")


def setup_function() -> None:
    _delete_fixture()


def teardown_function() -> None:
    _delete_fixture()


def _delete_fixture() -> None:
    # FK ON DELETE RESTRICT: 자식(utterances·meeting_bills) 먼저, 부모(meetings·bills) 나중.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM utterances WHERE meeting_id = %s", (TEST_MEETING_ID,))
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = %s", (TEST_MEETING_ID,))
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_BILL_IDS),))
        cur.execute("DELETE FROM meetings WHERE mnts_id = %s", (TEST_MEETING_ID,))
        conn.commit()


def _seed(*, utterance_roles: tuple[str, ...] = ("의원", "의원", "국무위원(장관)")) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date, comm_name)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (TEST_MEETING_ID, "TEST 회의", "상임위", date(2026, 1, 15), "테스트위원회"),
        )
        for idx, bill_id in enumerate(TEST_BILL_IDS, start=1):
            cur.execute(
                "INSERT INTO bills (bill_id, bill_no, bill_name) VALUES (%s, %s, %s)",
                (bill_id, f"999000{idx}", f"테스트 법안 {bill_id}"),
            )
            cur.execute(
                "INSERT INTO meeting_bills (meeting_id, bill_id) VALUES (%s, %s)",
                (TEST_MEETING_ID, bill_id),
            )
        for seq, role in enumerate(utterance_roles, start=1):
            cur.execute(
                """
                INSERT INTO utterances
                    (meeting_id, sequence, speaker_name, speaker_title, content, speaker_role)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (TEST_MEETING_ID, seq, "홍길동", "위원", "테스트 발언", role),
            )
        conn.commit()


def _fetch_context(bill_id: str) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, meeting_id, meeting_type, comm_name, conf_date,
                   linked_bill_count, utterance_count, utterances_by_role, evidence_scope
            FROM bill_meeting_contexts
            WHERE bill_id = %s
            """,
            (bill_id,),
        )
        row = cur.fetchone()
        cols = [c.name for c in cur.description]
    return dict(zip(cols, row)) if row else {}


def test_bill_in_crowded_meeting_reports_fanout_and_meeting_level_scope() -> None:
    _seed()

    ctx = _fetch_context("TEST_BMC_B1")

    assert ctx["linked_bill_count"] == 3
    assert ctx["evidence_scope"] == "meeting_level"
    assert ctx["meeting_type"] == "상임위"
    assert ctx["comm_name"] == "테스트위원회"
    assert ctx["conf_date"] == date(2026, 1, 15)


def test_each_linked_bill_gets_its_own_row_with_shared_fanout() -> None:
    _seed()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, linked_bill_count
            FROM bill_meeting_contexts
            WHERE meeting_id = %s
            ORDER BY bill_id
            """,
            (TEST_MEETING_ID,),
        )
        rows = cur.fetchall()

    assert rows == [
        ("TEST_BMC_B1", 3),
        ("TEST_BMC_B2", 3),
        ("TEST_BMC_B3", 3),
    ]


def test_utterance_count_and_role_breakdown_are_meeting_level() -> None:
    _seed(utterance_roles=("의원", "의원", "국무위원(장관)"))

    ctx = _fetch_context("TEST_BMC_B1")

    assert ctx["utterance_count"] == 3
    assert ctx["utterances_by_role"] == {"의원": 2, "국무위원(장관)": 1}


def test_meeting_without_utterances_reports_zero_not_null() -> None:
    _seed(utterance_roles=())

    ctx = _fetch_context("TEST_BMC_B1")

    assert ctx["utterance_count"] == 0
    assert ctx["utterances_by_role"] == {}
    assert ctx["linked_bill_count"] == 3
