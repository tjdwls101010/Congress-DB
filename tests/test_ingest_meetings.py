"""Slice 6 — meetings + meeting_bills 적재 검증."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.db import get_conn
from congress_db.ingest_meetings import (
    _fetch_vconfbill_rows_for_bills,
    _fetch_vconfbill_rows_for_bills_with_failures,
    _prune_stale_meetings,
    _select_vconfbill_bill_ids,
    ingest_meetings,
)
from congress_db.minutes_web_list import MinutesWebListCrawlResult, MinutesWebListMeeting

TEST_SOURCE_MEETINGS = (910001, 910002, 910003, 910004)
TEST_WEB_ONLY_MEETING = 910005
TEST_STALE_MEETING = 910099
TEST_MEETINGS = (*TEST_SOURCE_MEETINGS, TEST_WEB_ONLY_MEETING, TEST_STALE_MEETING)
TEST_BILLS = ("TEST_MEETING_BILL_1", "TEST_MEETING_BILL_2")


@pytest.fixture(autouse=True)
def clean_meeting_rows() -> None:
    _delete_meeting_rows()
    _insert_test_bills()
    yield
    _delete_meeting_rows()


def _delete_meeting_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM dead_letters WHERE source = 'minutes.html' AND item_key = ANY(%s)",
            ([str(mnts_id) for mnts_id in TEST_MEETINGS],),
        )
        cur.execute(
            """
            DELETE FROM ingest_runs
            WHERE summary @> '{"test_stale_meeting": true}'::jsonb
            """
        )
        cur.execute("DELETE FROM utterances WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM meeting_bills WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
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
    monkeypatch.setattr(
        "congress_db.ingest_meetings.collect_minutes_web_list",
        lambda: MinutesWebListCrawlResult(
            meetings=(
                _web_meeting(910001, "제22대 제435회 제2차 국회본회의 (2026. 05. 08.)", "본회의", date(2026, 5, 8)),
                _web_meeting(
                    910002,
                    "제22대 제435회 제1차 테스트위원회 법안심사소위원회 (2026. 05. 07.)",
                    "소위원회",
                    date(2026, 5, 7),
                    comm_name="테스트위원회 법안심사소위원회",
                ),
                _web_meeting(
                    910003,
                    "조사특별위원회 국정조사 회의록 제1차 (2026. 05. 09.)",
                    "국정조사",
                    date(2026, 5, 9),
                    comm_name="조사특별위원회",
                ),
                _web_meeting(
                    910004,
                    "인사청문특별위원회 인사청문회 회의록 제1차 (2026. 05. 10.)",
                    "인사청문회",
                    date(2026, 5, 10),
                    comm_name="인사청문특별위원회",
                ),
                _web_meeting(
                    TEST_WEB_ONLY_MEETING,
                    "웹목록전용 회의 제1차 (2026. 05. 11.)",
                    "상임위",
                    date(2026, 5, 11),
                    comm_name="웹목록위원회",
                ),
            ),
            html_unavailable=(),
        ),
    )
    _insert_existing_web_only_meeting_bill()

    first = ingest_meetings(
        calibration_limit=10,
        page_size=10,
        years=(2026,),
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "MEETINGS-PARALLEL-BENCHMARK.md",
    )
    vconf_calls_after_first = sum(1 for endpoint, _ in calls if endpoint == "VCONFBILLCONFLIST")
    second = ingest_meetings(
        calibration_limit=10,
        page_size=10,
        years=(2026,),
        benchmark_sample_size=1,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "MEETINGS-PARALLEL-BENCHMARK.md",
        vconfbill_fetch_mode="missing",
    )
    vconf_calls_after_second = sum(1 for endpoint, _ in calls if endpoint == "VCONFBILLCONFLIST")

    assert first.meeting_count == 5
    assert first.total_count == 5
    assert first.agenda_candidate_count == 2
    assert first.meeting_bill_count == 2
    assert first.selected_worker_count == 1
    assert first.new_meeting_ids == TEST_SOURCE_MEETINGS
    assert first.changed_meeting_ids == ()
    assert first.stale_meeting_ids == ()
    assert first.html_unavailable_mnts_ids == ()
    assert first.web_only_mnts_ids == ()
    assert first.openapi_only_mnts_ids == ()
    assert second.meeting_count == 5
    assert second.agenda_candidate_count == 2
    assert second.meeting_bill_count == 2
    assert second.new_meeting_ids == ()
    assert second.changed_meeting_ids == ()
    assert second.stale_meeting_ids == ()
    assert second.vconfbill_target_bill_count == 0
    assert second.vconfbill_skipped_bill_count == 2
    assert vconf_calls_after_second == vconf_calls_after_first
    assert (tmp_path / "MEETINGS-PARALLEL-BENCHMARK.md").exists()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id, meeting_type, is_temporary, is_appendix
            FROM meetings
            WHERE mnts_id = ANY(%s)
            ORDER BY mnts_id
            """,
            (list(TEST_MEETINGS),),
        )
        meetings = cur.fetchall()
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
        (910001, "본회의", False, False),
        (910002, "소위원회", False, False),
        (910003, "국정조사", False, False),
        (910004, "인사청문회", False, False),
        (910005, "상임위", False, False),
    ]
    assert meeting_bills == [
        (910001, "TEST_MEETING_BILL_1", "both"),
        (910002, "TEST_MEETING_BILL_2", "both"),
        (910005, "TEST_MEETING_BILL_2", "existing"),
    ]
    assert {endpoint for endpoint, _ in calls} >= {
        "nzbyfwhwaoanttzje",
        "ncwgseseafwbuheph",
        "VCONFAPIGCONFLIST",
        "VCONFPIPCONFLIST",
        "VCONFCFRMCONFLIST",
        "VCONFBILLCONFLIST",
    }


def test_prune_stale_meetings_removes_non_web_meeting_state() -> None:
    _insert_existing_web_only_meeting_bill()
    _insert_stale_meeting_state()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT mnts_id FROM meetings WHERE mnts_id <> %s", (TEST_STALE_MEETING,))
        canonical_ids = {row[0] for row in cur.fetchall()}
        stale_ids = _prune_stale_meetings(conn, canonical_ids)
        conn.commit()

    assert stale_ids == (TEST_STALE_MEETING,)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM meetings WHERE mnts_id = %s", (TEST_STALE_MEETING,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM meetings WHERE mnts_id = %s", (TEST_WEB_ONLY_MEETING,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM meeting_bills WHERE meeting_id = %s", (TEST_STALE_MEETING,))
        assert cur.fetchone()[0] == 0
        cur.execute(
            """
            SELECT COUNT(*)
            FROM dead_letters
            WHERE source = 'minutes.html'
              AND item_key = %s
            """,
            (str(TEST_STALE_MEETING),),
        )
        assert cur.fetchone()[0] == 0


def test_select_vconfbill_bill_ids_keeps_missing_and_touched_bills() -> None:
    _insert_existing_web_only_meeting_bill()
    agenda_rows = [
        {"meeting_id": 910001, "bill_id": "TEST_MEETING_BILL_1"},
        {"meeting_id": TEST_WEB_ONLY_MEETING, "bill_id": "TEST_MEETING_BILL_2"},
    ]

    target, skipped = _select_vconfbill_bill_ids(
        agenda_rows,
        fetch_mode="missing",
        touched_meeting_ids=set(),
    )

    assert target == ["TEST_MEETING_BILL_1"]
    assert skipped == ("TEST_MEETING_BILL_2",)

    target, skipped = _select_vconfbill_bill_ids(
        agenda_rows,
        fetch_mode="missing",
        touched_meeting_ids={TEST_WEB_ONLY_MEETING},
    )

    assert target == ["TEST_MEETING_BILL_1", "TEST_MEETING_BILL_2"]
    assert skipped == ()


def test_fetch_vconfbill_rows_for_bills_retries_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, int] = {}

    def fake_fetch(bill_id: str) -> list[dict[str, Any]]:
        calls[bill_id] = calls.get(bill_id, 0) + 1
        if bill_id == "TEST_MEETING_BILL_1" and calls[bill_id] == 1:
            raise RuntimeError("temporary DNS failure")
        return [{"BILL_ID": bill_id}]

    monkeypatch.setattr("congress_db.ingest_meetings._fetch_vconfbill_rows", fake_fetch)

    rows = _fetch_vconfbill_rows_for_bills(
        ["TEST_MEETING_BILL_1", "TEST_MEETING_BILL_2"],
        worker_count=2,
        retry_delays=(0.0,),
    )

    assert rows == {
        "TEST_MEETING_BILL_1": [{"BILL_ID": "TEST_MEETING_BILL_1"}],
        "TEST_MEETING_BILL_2": [{"BILL_ID": "TEST_MEETING_BILL_2"}],
    }
    assert calls["TEST_MEETING_BILL_1"] == 2
    assert calls["TEST_MEETING_BILL_2"] == 1


def test_fetch_vconfbill_rows_for_bills_raises_after_final_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch(bill_id: str) -> list[dict[str, Any]]:
        if bill_id == "TEST_MEETING_BILL_1":
            raise RuntimeError("persistent DNS failure")
        return [{"BILL_ID": bill_id}]

    monkeypatch.setattr("congress_db.ingest_meetings._fetch_vconfbill_rows", fake_fetch)

    with pytest.raises(RuntimeError, match="persistent failures"):
        _fetch_vconfbill_rows_for_bills(
            ["TEST_MEETING_BILL_1", "TEST_MEETING_BILL_2"],
            worker_count=2,
            retry_delays=(),
        )


def test_fetch_vconfbill_rows_for_bills_with_failures_returns_partial_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch(bill_id: str) -> list[dict[str, Any]]:
        if bill_id == "TEST_MEETING_BILL_1":
            raise RuntimeError("persistent DNS failure")
        return [{"BILL_ID": bill_id}]

    monkeypatch.setattr("congress_db.ingest_meetings._fetch_vconfbill_rows", fake_fetch)

    rows, failures = _fetch_vconfbill_rows_for_bills_with_failures(
        ["TEST_MEETING_BILL_1", "TEST_MEETING_BILL_2"],
        worker_count=2,
        retry_delays=(),
    )

    assert rows == {"TEST_MEETING_BILL_2": [{"BILL_ID": "TEST_MEETING_BILL_2"}]}
    assert [(failure.bill_id, failure.error) for failure in failures] == [
        ("TEST_MEETING_BILL_1", "after 1 attempts: persistent DNS failure")
    ]


def _web_meeting(
    mnts_id: int,
    title: str,
    meeting_type: str,
    conf_date: date,
    *,
    comm_name: str | None = None,
) -> MinutesWebListMeeting:
    return MinutesWebListMeeting(
        mnts_id=mnts_id,
        title=title,
        meeting_type=meeting_type,
        conf_date=conf_date,
        comm_name=comm_name,
        session_no=None,
        degree=None,
        is_temporary=False,
        is_appendix=False,
        detail_url=f"https://record.assembly.go.kr/assembly/viewer/minutes/xml.do?id={mnts_id}&type=view",
        source_class_id=0,
        source_class_label="test",
    )


def _insert_existing_web_only_meeting_bill() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date, comm_name)
            VALUES (
                %s,
                '웹목록전용 회의 제1차 (2026. 05. 11.)',
                '상임위',
                '2026-05-11',
                '웹목록위원회'
            )
            """,
            (TEST_WEB_ONLY_MEETING,),
        )
        cur.execute(
            """
            INSERT INTO meeting_bills (meeting_id, bill_id, source)
            VALUES (%s, 'TEST_MEETING_BILL_2', 'existing')
            """,
            (TEST_WEB_ONLY_MEETING,),
        )
        conn.commit()


def _insert_stale_meeting_state() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date, comm_name)
            VALUES (%s, '웹목록에 없는 회의', '상임위', '2026-05-12', '테스트위원회')
            """,
            (TEST_STALE_MEETING,),
        )
        cur.execute(
            """
            INSERT INTO meeting_bills (meeting_id, bill_id, source)
            VALUES (%s, 'TEST_MEETING_BILL_1', 'existing')
            """,
            (TEST_STALE_MEETING,),
        )
        cur.execute(
            """
            INSERT INTO ingest_runs (mode, status, summary)
            VALUES ('backfill', 'failed', '{"test_stale_meeting": true}'::jsonb)
            RETURNING id
            """
        )
        run_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO dead_letters (run_id, source, stage, item_key, payload, error, status)
            VALUES (
                %s,
                'minutes.html',
                'fetch',
                %s,
                '{}'::jsonb,
                'stale web detail',
                'pending'
            )
            """,
            (run_id, str(TEST_STALE_MEETING)),
        )
        conn.commit()
