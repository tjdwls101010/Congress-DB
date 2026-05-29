"""Slice 8 — session_groups 자동 감지 검증."""

from __future__ import annotations

import pytest

from congress_db.db import get_conn
from congress_db.session_groups import (
    SessionUtterance,
    detect_sessions_from_stream,
    ingest_session_groups,
    should_skip_session_detection,
)

TEST_MEETINGS = (930101, 930102)
TEST_MEMBERS = ("TEST_SG_MEMBER_1", "TEST_SG_MEMBER_2")


@pytest.fixture(autouse=True)
def clean_session_group_rows() -> None:
    _delete_rows()
    _insert_rows()
    yield
    _delete_rows()


def _delete_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE utterances SET session_group_id = NULL WHERE meeting_id = ANY(%s)",
            (list(TEST_MEETINGS),),
        )
        cur.execute("DELETE FROM session_groups WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM utterances WHERE meeting_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM meetings WHERE mnts_id = ANY(%s)", (list(TEST_MEETINGS),))
        cur.execute("DELETE FROM members WHERE mona_cd = ANY(%s)", (list(TEST_MEMBERS),))
        conn.commit()


def _insert_rows() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO members (mona_cd, hg_nm)
            VALUES
                ('TEST_SG_MEMBER_1', '김테스트'),
                ('TEST_SG_MEMBER_2', '가상일')
            """
        )
        cur.execute(
            """
            INSERT INTO meetings (mnts_id, title, meeting_type, conf_date)
            VALUES
                (930101, '테스트 위원회', '상임위', '2026-05-20'),
                (930102, '테스트 본회의', '본회의', '2026-05-21')
            """
        )
        cur.execute(
            """
            INSERT INTO utterances (
                meeting_id, sequence, speaker_name, speaker_title,
                speaker_mona_cd, content
            )
            VALUES
                (930101, 1, '위원장', '위원장', NULL, '김테스트 위원님 질의해 주십시오.'),
                (930101, 2, '김테스트', '위원', 'TEST_SG_MEMBER_1', '첫 질의입니다.'),
                (930101, 3, '홍길동', '장관', NULL, '답변입니다.'),
                (930101, 4, '김테스트', '위원', 'TEST_SG_MEMBER_1', '추가 질의입니다.'),
                (930101, 5, '위원장', '위원장', NULL, '가상일 위원님 질의해 주십시오.'),
                (930101, 6, '가상일', '위원', 'TEST_SG_MEMBER_2', '다음 질의입니다.'),
                (930101, 7, '이답변', '차관', NULL, '추가 답변입니다.'),
                (930102, 1, '의장', '의장', NULL, '김테스트 의원님 발언하십시오.'),
                (930102, 2, '김테스트', '의원', 'TEST_SG_MEMBER_1', '본회의 발언입니다.')
            """
        )
        conn.commit()


def _utterances() -> list[SessionUtterance]:
    return [
        SessionUtterance(1, "위원장", "위원장", None, "김테스트 위원님 질의해 주십시오."),
        SessionUtterance(2, "김테스트", "위원", "TEST_SG_MEMBER_1", "첫 질의입니다."),
        SessionUtterance(3, "홍길동", "장관", None, "답변입니다."),
        SessionUtterance(4, "김테스트", "위원", "TEST_SG_MEMBER_1", "추가 질의입니다."),
        SessionUtterance(5, "위원장", "위원장", None, "가상일 위원님 질의해 주십시오."),
        SessionUtterance(6, "가상일", "위원", "TEST_SG_MEMBER_2", "다음 질의입니다."),
        SessionUtterance(7, "이답변", "차관", None, "추가 답변입니다."),
    ]


def test_detect_sessions_from_stream_builds_questioner_groups() -> None:
    groups = detect_sessions_from_stream(
        meeting_id=930101,
        meeting_type="상임위",
        title="테스트 위원회",
        utterances=_utterances(),
    )

    assert [group.questioner_mona_cd for group in groups] == [
        "TEST_SG_MEMBER_1",
        "TEST_SG_MEMBER_2",
    ]
    assert (groups[0].seq_start, groups[0].seq_end) == (1, 4)
    assert (groups[0].respondents[0].name, groups[0].respondents[0].title) == ("홍길동", "장관")
    assert groups[0].utterance_count == 4
    assert groups[0].total_chars == sum(len(utterance.content) for utterance in _utterances()[:4])
    assert (groups[1].seq_start, groups[1].seq_end) == (5, 7)


def test_detect_sessions_treats_audit_banjang_as_presider() -> None:
    groups = detect_sessions_from_stream(
        meeting_id=930101,
        meeting_type="국정감사",
        title="테스트 국정감사",
        utterances=[
            SessionUtterance(1, "감사반장", "반장", None, "김테스트 위원님 질의해 주십시오."),
            SessionUtterance(2, "김테스트", "위원", "TEST_SG_MEMBER_1", "질의입니다."),
            SessionUtterance(3, "홍길동", "증인", None, "답변입니다."),
        ],
    )

    assert len(groups) == 1
    assert groups[0].questioner_mona_cd == "TEST_SG_MEMBER_1"
    assert groups[0].respondents[0].title == "증인"


def test_detect_sessions_finds_named_questioner_after_interjections() -> None:
    groups = detect_sessions_from_stream(
        meeting_id=930101,
        meeting_type="국정감사",
        title="테스트 국정감사",
        utterances=[
            SessionUtterance(1, "감사반장", "반장", None, "가상일 위원님 질의하십시오."),
            SessionUtterance(2, "김테스트", "위원", "TEST_SG_MEMBER_1", "잠깐만요."),
            SessionUtterance(3, "감사반장", "반장", None, "질의하십시오."),
            SessionUtterance(4, "가상일", "위원", "TEST_SG_MEMBER_2", "질의입니다."),
            SessionUtterance(5, "홍길동", "증인", None, "답변입니다."),
        ],
    )

    assert len(groups) == 1
    assert groups[0].questioner_mona_cd == "TEST_SG_MEMBER_2"
    assert (groups[0].seq_start, groups[0].seq_end) == (4, 5)


def test_detect_sessions_skips_groups_without_respondents() -> None:
    groups = detect_sessions_from_stream(
        meeting_id=930101,
        meeting_type="상임위",
        title="테스트 위원회",
        utterances=[
            SessionUtterance(1, "위원장", "위원장", None, "김테스트 위원님?"),
            SessionUtterance(2, "김테스트", "위원", "TEST_SG_MEMBER_1", "없습니다."),
        ],
    )

    assert groups == []


def test_should_skip_session_detection_for_plenary_and_subcommittee_titles() -> None:
    assert should_skip_session_detection("본회의", "테스트 본회의") is True
    assert should_skip_session_detection("상임위", "법안심사제1소위원회") is True
    assert should_skip_session_detection("상임위", "테스트 위원회") is False


def test_ingest_session_groups_replaces_rows_idempotently() -> None:
    first = ingest_session_groups(meeting_ids=TEST_MEETINGS)
    second = ingest_session_groups(meeting_ids=TEST_MEETINGS)

    assert first.meeting_count == 2
    assert first.skipped_meeting_count == 1
    assert first.group_count == 2
    assert first.utterance_link_count == 7
    assert second.group_count == 2
    assert second.utterance_link_count == 7

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT questioner_mona_cd, respondents, seq_start, seq_end,
                   utterance_count, total_chars
            FROM session_groups
            WHERE meeting_id = 930101
            ORDER BY seq_start
            """
        )
        groups = cur.fetchall()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM utterances
            WHERE meeting_id = 930102 AND session_group_id IS NOT NULL
            """
        )
        plenary_link_count = cur.fetchone()[0]

    assert len(groups) == 2
    assert groups[0][0] == "TEST_SG_MEMBER_1"
    assert groups[0][1] == [{"name": "홍길동", "title": "장관"}]
    assert groups[0][2:5] == (1, 4, 4)
    assert groups[1][0] == "TEST_SG_MEMBER_2"
    assert groups[1][1] == [{"name": "이답변", "title": "차관"}]
    assert plenary_link_count == 0
