"""Slice 6 — meetings + agenda_items + meeting_bills 적재 검증."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.db import get_conn
from congress_db.ingest_meetings import ingest_meetings

TEST_MEETINGS = (910001, 910002, 910003, 910004)
TEST_BILLS = ("TEST_MEETING_BILL_1", "TEST_MEETING_BILL_2")


@pytest.fixture(autouse=True)
def clean_meeting_rows() -> None:
    _delete_meeting_rows()
    _insert_test_bills()
    yield
    _delete_meeting_rows()


def _delete_meeting_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM agenda_items WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM meetings WHERE mnts_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM bills WHERE bill_id = ANY(%s)", (list(TEST_BILLS),))
        conn.commit()


def _insert_test_bills() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bills (bill_id, bill_no, bill_name)
            VALUES
                ('TEST_MEETING_BILL_1', '9908348', '테스트 회의 법안 1'),
                ('TEST_MEETING_BILL_2', '9906993', '테스트 회의 법안 2')
            ON CONFLICT (bill_id) DO NOTHING
            """
        )
        conn.commit()


def _envelope(endpoint: str, total: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        endpoint: [
            {"head": [{"list_total_count": total}, {"RESULT": {"CODE": "INFO-000"}}]},
            {"row": rows},
        ]
    }


def _no_data() -> dict[str, Any]:
    return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}


def test_ingest_meetings_normalizes_sources_and_bills_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    plenary_rows = [
        {
            "CONFER_NUM": "910001",
            "CONF_ID": "NTEST001",
            "TITLE": "제22대 제435회 제2차 국회본회의 (2026년 05월 08일)",
            "CLASS_NAME": "국회본회의",
            "CONF_DATE": "2026-05-08",
            "DAE_NUM": "22",
            "SUB_NAME": "1. 항공안전법 일부개정법률안(의안번호 9908348)",
            "PDF_LINK_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910001",
            "VOD_LINK_URL": "https://example.com/vod/910001",
            "CONF_LINK_URL": "https://example.com/conf/910001",
        }
    ]
    committee_rows = [
        {
            "CONFER_NUM": "910002",
            "CONF_ID": "NTEST002",
            "TITLE": "제22대 제435회 제1차 테스트위원회 법안심사소위원회 (2026년 05월 07일)",
            "CLASS_NAME": "상임위원회",
            "COMM_NAME": "테스트위원회 법안심사소위원회",
            "DEPT_CD": "TESTCMT",
            "CONF_DATE": "2026-05-07",
            "DAE_NUM": "22",
            "SUB_NAME": "2. 인천광역시 서구 명칭 변경에 관한 법률안(의안번호 9906993)",
            "PDF_LINK_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910002",
        }
    ]
    audit_rows = [
        {
            "CONF_ID": "NTEST002",
            "CONF_KND": "국정감사 회의록",
            "ERACO": "제22대",
            "SESS": "제435회",
            "DGR": "제1차",
            "CONF_DT": "20260507        ",
            "CMIT_NM": "테스트위원회",
            "CMIT_CD": "TESTCMT",
            "DOWN_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910002",
        }
    ]
    investigation_rows = [
        {
            "CONF_ID": "NTEST003",
            "CONF_KND": "국정조사 회의록",
            "ERACO": "제22대",
            "SESS": "제435회",
            "DGR": "제1차",
            "CONF_DT": "20260509",
            "CMIT_NM": "조사특별위원회",
            "CMIT_CD": "TESTPIP",
            "DOWN_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910003",
        }
    ]
    confirmation_rows = [
        {
            "CONF_ID": "NTEST004",
            "CONF_KND": "인사청문회 회의록",
            "ERACO": "제22대",
            "SESS": "제435회",
            "DGR": "제1차",
            "CONF_DT": "20260510",
            "CMIT_NM": "인사청문특별위원회",
            "CMIT_CD": "TESTCFRM",
            "DOWN_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910004",
        }
    ]
    vconfbill_rows = {
        "TEST_MEETING_BILL_1": [
            {
                "BILL_ID": "TEST_MEETING_BILL_1",
                "BILL_NM": "1. 항공안전법 일부개정법률안(의안번호 9908348)",
                "CONF_ID": "NTEST001",
                "CONF_DT": "20260508",
                "DOWN_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910001",
            }
        ],
        "TEST_MEETING_BILL_2": [
            {
                "BILL_ID": "TEST_MEETING_BILL_2",
                "BILL_NM": "2. 인천광역시 서구 명칭 변경에 관한 법률안(의안번호 9906993)",
                "CONF_ID": "NTEST002",
                "CONF_DT": "20260507",
                "DOWN_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=910002",
            },
            {
                "BILL_ID": "TEST_MEETING_BILL_2",
                "BILL_NM": "99. 샘플 외 회의(의안번호 9906993)",
                "CONF_ID": "NTEST999",
                "CONF_DT": "20260511",
                "DOWN_URL": "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=919999",
            },
        ],
    }
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        endpoint = url.rsplit("/", 1)[-1]
        params = kwargs["params"]
        calls.append((endpoint, dict(params)))
        response = MagicMock()
        response.raise_for_status = MagicMock()

        if endpoint in {"nzbyfwhwaoanttzje", "ncwgseseafwbuheph"} and "DAE_NUM" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "nzbyfwhwaoanttzje":
            response.json.return_value = _envelope(endpoint, total=1, rows=plenary_rows)
        elif endpoint == "ncwgseseafwbuheph":
            response.json.return_value = _envelope(endpoint, total=1, rows=committee_rows)
        elif endpoint in {"VCONFAPIGCONFLIST", "VCONFPIPCONFLIST", "VCONFCFRMCONFLIST"} and "ERACO" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "VCONFAPIGCONFLIST":
            response.json.return_value = _envelope(endpoint, total=1, rows=audit_rows)
        elif endpoint == "VCONFPIPCONFLIST":
            response.json.return_value = _envelope(endpoint, total=1, rows=investigation_rows)
        elif endpoint == "VCONFCFRMCONFLIST":
            response.json.return_value = _envelope(endpoint, total=1, rows=confirmation_rows)
        elif endpoint == "VCONFBILLCONFLIST" and "DAE_NUM" not in params:
            response.json.return_value = _no_data()
        elif endpoint == "VCONFBILLCONFLIST":
            rows = vconfbill_rows[params["BILL_ID"]]
            response.json.return_value = _envelope(endpoint, total=len(rows), rows=rows)
        else:
            raise AssertionError(endpoint)
        return response

    monkeypatch.setattr("congress_db.api_client.requests.get", fake_get)

    first = ingest_meetings(
        calibration_limit=10,
        page_size=10,
        years=(2026,),
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "MEETINGS-PARALLEL-BENCHMARK.md",
    )
    second = ingest_meetings(
        calibration_limit=10,
        page_size=10,
        years=(2026,),
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "MEETINGS-PARALLEL-BENCHMARK.md",
    )

    assert first.meeting_count == 4
    assert first.agenda_item_count == 2
    assert first.meeting_bill_count == 2
    assert first.selected_worker_count == 1
    assert second.meeting_count == 4
    assert second.agenda_item_count == 2
    assert second.meeting_bill_count == 2
    assert (tmp_path / "MEETINGS-PARALLEL-BENCHMARK.md").exists()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id, meeting_type, source_api
            FROM meetings
            WHERE mnts_id = ANY(%s)
            ORDER BY mnts_id
            """,
            (list(TEST_MEETINGS),),
        )
        meetings = cur.fetchall()
        cur.execute(
            """
            SELECT meeting_id, order_no, sub_name, bill_id
            FROM agenda_items
            WHERE meeting_id = ANY(%s)
            ORDER BY meeting_id, order_no
            """,
            (list(TEST_MEETINGS),),
        )
        agenda_items = cur.fetchall()
        cur.execute(
            """
            SELECT meeting_id, bill_id, source
            FROM meeting_bills
            WHERE meeting_id = ANY(%s)
            ORDER BY meeting_id, bill_id
            """,
            (list(TEST_MEETINGS),),
        )
        meeting_bills = cur.fetchall()

    assert meetings == [
        (910001, "본회의", "nzbyfwhwaoanttzje"),
        (910002, "소위원회", "multi"),
        (910003, "국정조사", "VCONFPIPCONFLIST"),
        (910004, "인사청문회", "VCONFCFRMCONFLIST"),
    ]
    assert agenda_items == [
        (
            910001,
            1,
            "1. 항공안전법 일부개정법률안(의안번호 9908348)",
            "TEST_MEETING_BILL_1",
        ),
        (
            910002,
            2,
            "2. 인천광역시 서구 명칭 변경에 관한 법률안(의안번호 9906993)",
            "TEST_MEETING_BILL_2",
        ),
    ]
    assert meeting_bills == [
        (910001, "TEST_MEETING_BILL_1", "both"),
        (910002, "TEST_MEETING_BILL_2", "both"),
    ]
    assert {endpoint for endpoint, _ in calls} >= {
        "nzbyfwhwaoanttzje",
        "ncwgseseafwbuheph",
        "VCONFAPIGCONFLIST",
        "VCONFPIPCONFLIST",
        "VCONFCFRMCONFLIST",
        "VCONFBILLCONFLIST",
    }
