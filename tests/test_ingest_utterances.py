"""Slice 7 — utterances 적재 검증."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from congress_db.db import get_conn
from congress_db.ingest_utterances import ingest_utterances

TEST_MEETINGS = (920101, 920102)
TEST_MEMBERS = ("TEST_UTT_MEMBER_1", "TEST_UTT_MEMBER_2")


@pytest.fixture(autouse=True)
def clean_utterance_rows() -> None:
    _delete_utterance_rows()
    _insert_test_rows()
    yield
    _delete_utterance_rows()


def _delete_utterance_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM utterances WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM meetings WHERE mnts_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM members WHERE mona_cd = ANY(%s)", (list(TEST_MEMBERS),))
        conn.commit()


def _insert_test_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO members (mona_cd, hg_nm)
            VALUES
                ('TEST_UTT_MEMBER_1', '가상일'),
                ('TEST_UTT_MEMBER_2', '김테스트')
            """
        )
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date)
            VALUES
                (920101, '테스트 위원회', '상임위', '2026-05-20'),
                (920102, '테스트 본회의', '본회의', '2026-05-21')
            """
        )
        conn.commit()


def _html(mnts_id: int) -> str:
    if mnts_id == 920101:
        return """
        <html><body>
          <h2>테스트 위원회(2026.05.20.)</h2>
          <div class="minutes_body">
            <div id="spk_1" class="speaker" data-name="가상일" data-pos="위원">
              <div class="talk"><div class="txt">의원 발언입니다.</div></div>
            </div>
            <div id="spk_2" class="speaker" data-name="홍길동" data-pos="장관">
              <div class="talk"><div class="txt">정부 답변입니다.</div></div>
            </div>
          </div>
        </body></html>
        """
    return """
    <html><body>
      <h2>테스트 본회의(2026.05.21.)</h2>
      <div class="minutes_body">
        <div id="spk_1" class="speaker" data-name="김테스트" data-pos="의원">
          <div class="talk"><div class="txt">본회의 발언입니다.</div></div>
        </div>
      </div>
    </body></html>
    """


def test_ingest_utterances_scrapes_and_upserts_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        mnts_id = int(kwargs["params"]["id"])
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.apparent_encoding = "utf-8"
        response.text = _html(mnts_id)
        return response

    monkeypatch.setattr("congress_db.scrape_minutes.requests.get", fake_get)

    first = ingest_utterances(
        calibration_limit=2,
        benchmark_sample_size=1,
        meeting_ids=TEST_MEETINGS,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )
    second = ingest_utterances(
        calibration_limit=2,
        benchmark_sample_size=1,
        meeting_ids=TEST_MEETINGS,
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert first.meeting_count == 2
    assert first.utterance_count == 3
    assert first.scrape_error_count == 0
    assert first.selected_worker_count == 1
    assert second.utterance_count == 3

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT meeting_id, sequence, speaker_name, speaker_title, speaker_mona_cd, content
            FROM utterances
            WHERE meeting_id = ANY(%s)
            ORDER BY meeting_id, sequence
            """,
            (list(TEST_MEETINGS),),
        )
        rows = cur.fetchall()

    assert rows == [
        (920101, 1, "가상일", "위원", "TEST_UTT_MEMBER_1", "의원 발언입니다."),
        (920101, 2, "홍길동", "장관", None, "정부 답변입니다."),
        (920102, 1, "김테스트", "의원", "TEST_UTT_MEMBER_2", "본회의 발언입니다."),
    ]
    assert "Scraping Stage" in (tmp_path / "PARALLEL-BENCHMARK.md").read_text()


def test_ingest_utterances_retries_failed_meetings_in_final_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    call_counts: dict[int, int] = {}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        mnts_id = int(kwargs["params"]["id"])
        call_counts[mnts_id] = call_counts.get(mnts_id, 0) + 1
        if mnts_id == 920102 and call_counts[mnts_id] == 1:
            raise RuntimeError("temporary overload")

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.apparent_encoding = "utf-8"
        response.text = _html(mnts_id)
        return response

    monkeypatch.setattr("congress_db.scrape_minutes.requests.get", fake_get)

    result = ingest_utterances(
        calibration_limit=2,
        benchmark_sample_size=1,
        meeting_ids=TEST_MEETINGS,
        retry_delays=(),
        worker_levels=(2,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert result.scraped_meeting_count == 2
    assert result.scrape_error_count == 0
    assert result.utterance_count == 3
    assert call_counts[920102] == 2


def test_ingest_utterances_retries_metadata_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    call_counts: dict[int, int] = {}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        mnts_id = int(kwargs["params"]["id"])
        call_counts[mnts_id] = call_counts.get(mnts_id, 0) + 1

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.apparent_encoding = "utf-8"
        if mnts_id == 920102 and call_counts[mnts_id] == 1:
            response.text = _html(920101)
        else:
            response.text = _html(mnts_id)
        return response

    monkeypatch.setattr("congress_db.scrape_minutes.requests.get", fake_get)

    result = ingest_utterances(
        calibration_limit=2,
        benchmark_sample_size=1,
        meeting_ids=TEST_MEETINGS,
        retry_delays=(),
        worker_levels=(2,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
    )

    assert result.scraped_meeting_count == 2
    assert result.scrape_error_count == 0
    assert result.utterance_count == 3
    assert call_counts[920102] == 2

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT speaker_name, content
            FROM utterances
            WHERE meeting_id = 920102
            ORDER BY sequence
            """
        )
        rows = cur.fetchall()

    assert rows == [("김테스트", "본회의 발언입니다.")]


def test_ingest_utterances_aborts_when_no_worker_meets_error_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.apparent_encoding = "utf-8"
        response.text = "<html><body><h2>빈 회의록</h2></body></html>"
        return response

    monkeypatch.setattr("congress_db.scrape_minutes.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="did not find an acceptable worker count"):
        ingest_utterances(
            calibration_limit=1,
            benchmark_sample_size=1,
            meeting_ids=(920101,),
            retry_delays=(),
            worker_levels=(1,),
            benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
        )


def test_ingest_utterances_returns_structured_failures_when_partial_allowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    call_counts: dict[int, int] = {}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        mnts_id = int(kwargs["params"]["id"])
        call_counts[mnts_id] = call_counts.get(mnts_id, 0) + 1
        if mnts_id == 920102:
            raise RuntimeError("blocked by remote")

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.apparent_encoding = "utf-8"
        response.text = _html(mnts_id)
        return response

    monkeypatch.setattr("congress_db.scrape_minutes.requests.get", fake_get)

    result = ingest_utterances(
        calibration_limit=2,
        benchmark_sample_size=1,
        meeting_ids=TEST_MEETINGS,
        retry_delays=(),
        worker_levels=(1,),
        benchmark_output_path=tmp_path / "PARALLEL-BENCHMARK.md",
        allow_partial=True,
    )

    assert result.scraped_meeting_count == 1
    assert result.scrape_error_count == 1
    assert result.scrape_failures[0].mnts_id == 920102
    assert "blocked by remote" in result.scrape_failures[0].error
    assert call_counts[920102] == 2
