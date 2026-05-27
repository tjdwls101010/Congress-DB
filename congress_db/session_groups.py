"""Q&A session_group 자동 감지."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from psycopg.types.json import Jsonb

from .db import get_conn
from .progress import ProgressReporter

PRESIDER_SUFFIXES = (
    "의장",
    "부의장",
    "의장대리",
    "위원장",
    "부위원장",
    "위원장대리",
    "소위원장",
    "소위원장대리",
    "반장",
    "반장대리",
)
QUESTIONER_TITLES = frozenset({"위원", "의원"})
NON_RESPONDENT_TITLES = frozenset({"위원", "의원", "반장", "반장대리", "의사국장"})
SKIP_TITLE_RE = re.compile(r"(?:소위원회|조세소위|법안심사.*소위|예산결산.*소위|안건조정위원회)")
SKIP_MEETING_TYPES = frozenset({"본회의", "소위원회"})


@dataclass(frozen=True)
class SessionUtterance:
    """감지 알고리즘이 쓰는 발언."""

    sequence: int
    speaker_name: str
    speaker_title: str
    speaker_mona_cd: str | None
    content: str


@dataclass(frozen=True)
class Respondent:
    """Q&A 그룹 안의 답변자."""

    name: str
    title: str


@dataclass(frozen=True)
class SessionGroup:
    """DB 적재 전 Q&A 그룹."""

    meeting_id: int
    questioner_mona_cd: str
    respondents: tuple[Respondent, ...]
    seq_start: int
    seq_end: int
    utterance_count: int
    total_chars: int


@dataclass(frozen=True)
class IngestSessionGroupsResult:
    """session_groups 적재 결과."""

    meeting_count: int
    skipped_meeting_count: int
    group_count: int
    utterance_link_count: int


def should_skip_session_detection(meeting_type: str, title: str) -> bool:
    """회의 유형·제목상 Q&A 그룹이 부적합하면 True."""
    return meeting_type in SKIP_MEETING_TYPES or bool(SKIP_TITLE_RE.search(title or ""))


def detect_sessions(meeting_id: int) -> list[SessionGroup]:
    """DB의 한 회의 발언 stream에서 Q&A 그룹을 감지한다."""
    with get_conn() as conn, conn.cursor() as cur:
        groups, _ = _detect_sessions_with_cursor(cur, meeting_id)
    return groups


def _detect_sessions_with_cursor(cur: object, meeting_id: int) -> tuple[list[SessionGroup], bool]:
    cur.execute(
        """
        SELECT title, meeting_type
        FROM meetings
        WHERE mnts_id = %s
        """,
        (meeting_id,),
    )
    meeting = cur.fetchone()
    if meeting is None:
        raise ValueError(f"meeting not found: {meeting_id}")

    cur.execute(
        """
        SELECT sequence, speaker_name, speaker_title, speaker_mona_cd, content
        FROM utterances
        WHERE meeting_id = %s
        ORDER BY sequence
        """,
        (meeting_id,),
    )
    utterances = [
        SessionUtterance(
            sequence=row[0],
            speaker_name=row[1],
            speaker_title=row[2],
            speaker_mona_cd=row[3],
            content=row[4],
        )
        for row in cur.fetchall()
    ]
    title, meeting_type = meeting
    skipped = should_skip_session_detection(meeting_type, title)
    return detect_sessions_from_stream(
        meeting_id=meeting_id,
        meeting_type=meeting_type,
        title=title,
        utterances=utterances,
    ), skipped


def detect_sessions_from_stream(
    *,
    meeting_id: int,
    meeting_type: str,
    title: str,
    utterances: Sequence[SessionUtterance],
) -> list[SessionGroup]:
    """발언 stream만으로 Q&A 그룹을 감지한다."""
    if should_skip_session_detection(meeting_type, title) or not utterances:
        return []

    nominations = _merge_consecutive(_find_nominations(utterances))
    if not nominations:
        return []

    max_seq = max(utterance.sequence for utterance in utterances)
    groups: list[SessionGroup] = []
    for index, (seq_start, questioner_mona_cd) in enumerate(nominations):
        seq_end = nominations[index + 1][0] - 1 if index + 1 < len(nominations) else max_seq
        range_utterances = [
            utterance
            for utterance in utterances
            if seq_start <= utterance.sequence <= seq_end
        ]
        if not range_utterances:
            continue
        respondents = _respondents(range_utterances)
        if not respondents:
            continue
        groups.append(
            SessionGroup(
                meeting_id=meeting_id,
                questioner_mona_cd=questioner_mona_cd,
                respondents=respondents,
                seq_start=seq_start,
                seq_end=seq_end,
                utterance_count=len(range_utterances),
                total_chars=sum(len(utterance.content) for utterance in range_utterances),
            )
        )
    return groups


def ingest_session_groups(
    *,
    calibration_limit: int = 500,
    meeting_ids: Sequence[int] | None = None,
) -> IngestSessionGroupsResult:
    """감지된 Q&A 그룹을 `session_groups`와 `utterances`에 적재한다."""
    target_meeting_ids = list(meeting_ids or _load_target_meeting_ids(calibration_limit))
    print(f"[ingest-session-groups] target meetings={len(target_meeting_ids)}", flush=True)

    detected_by_meeting: dict[int, list[SessionGroup]] = {}
    skipped_meeting_count = 0
    progress = ProgressReporter("session group detection", len(target_meeting_ids))
    progress.start()
    with get_conn() as conn, conn.cursor() as cur:
        for meeting_id in target_meeting_ids:
            groups, skipped = _detect_sessions_with_cursor(cur, meeting_id)
            detected_by_meeting[meeting_id] = groups
            if skipped:
                skipped_meeting_count += 1
            progress.advance()
    progress.finish()

    with get_conn() as conn:
        _replace_session_groups_for_meetings(conn, target_meeting_ids)
        group_count, link_count = _insert_session_groups(conn, detected_by_meeting)
        conn.commit()

    return IngestSessionGroupsResult(
        meeting_count=len(target_meeting_ids),
        skipped_meeting_count=skipped_meeting_count,
        group_count=group_count,
        utterance_link_count=link_count,
    )


def _find_nominations(utterances: Sequence[SessionUtterance]) -> list[tuple[int, str]]:
    nominations: list[tuple[int, str]] = []
    for index, utterance in enumerate(utterances):
        if not _is_chair(utterance.speaker_title):
            continue

        nomination = _questioner_nomination(utterances, index)
        if nomination is not None:
            nominations.append(nomination)

    return sorted(
        [(sequence, mona_cd) for sequence, mona_cd in nominations if mona_cd],
        key=lambda item: item[0],
    )


def _questioner_nomination(
    utterances: Sequence[SessionUtterance],
    chair_index: int,
) -> tuple[int, str] | None:
    chair_utterance = utterances[chair_index]
    next_questioner = _next_questioner(utterances, chair_index + 1)
    if (
        next_questioner is not None
        and next_questioner.speaker_name in chair_utterance.content
        and next_questioner.speaker_mona_cd
    ):
        return chair_utterance.sequence, next_questioner.speaker_mona_cd

    named_questioner = _named_questioner_after_interjections(
        chair_utterance,
        utterances[chair_index + 1 :],
    )
    if named_questioner is None:
        return None
    return named_questioner.sequence, named_questioner.speaker_mona_cd or ""


def _named_questioner_after_interjections(
    chair_utterance: SessionUtterance,
    following: Sequence[SessionUtterance],
) -> SessionUtterance | None:
    by_mona_cd: dict[str, SessionUtterance] = {}
    for utterance in following:
        if not utterance.speaker_mona_cd or utterance.speaker_title not in QUESTIONER_TITLES:
            continue
        if utterance.speaker_name not in chair_utterance.content:
            continue
        by_mona_cd.setdefault(utterance.speaker_mona_cd, utterance)

    if len(by_mona_cd) != 1:
        return None
    return next(iter(by_mona_cd.values()))


def _merge_consecutive(nominations: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if not nominations:
        return []
    merged = [nominations[0]]
    for sequence, mona_cd in nominations[1:]:
        if mona_cd != merged[-1][1]:
            merged.append((sequence, mona_cd))
    return merged


def _next_questioner(
    utterances: Sequence[SessionUtterance],
    start_index: int,
) -> SessionUtterance | None:
    for utterance in utterances[start_index:]:
        if utterance.speaker_mona_cd and utterance.speaker_title in QUESTIONER_TITLES:
            return utterance
    return None


def _respondents(utterances: Sequence[SessionUtterance]) -> tuple[Respondent, ...]:
    respondents: list[Respondent] = []
    seen: set[tuple[str, str]] = set()
    for utterance in utterances:
        if not _is_respondent(utterance.speaker_title):
            continue
        key = (utterance.speaker_name, utterance.speaker_title)
        if key in seen:
            continue
        seen.add(key)
        respondents.append(Respondent(name=utterance.speaker_name, title=utterance.speaker_title))
    return tuple(respondents)


def _is_chair(speaker_title: str) -> bool:
    return any(speaker_title.endswith(suffix) for suffix in PRESIDER_SUFFIXES)


def _is_respondent(speaker_title: str) -> bool:
    if speaker_title in NON_RESPONDENT_TITLES:
        return False
    return not _is_chair(speaker_title)


def _load_target_meeting_ids(limit: int) -> list[int]:
    if limit <= 0:
        raise ValueError("calibration_limit must be positive")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.mnts_id
            FROM meetings m
            WHERE EXISTS (
                SELECT 1 FROM utterances u WHERE u.meeting_id = m.mnts_id
            )
            ORDER BY m.conf_date DESC, m.mnts_id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [row[0] for row in cur.fetchall()]


def _replace_session_groups_for_meetings(conn: object, meeting_ids: list[int]) -> None:
    if not meeting_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE utterances SET session_group_id = NULL WHERE meeting_id = ANY(%s)",
            (meeting_ids,),
        )
        cur.execute("DELETE FROM session_groups WHERE meeting_id = ANY(%s)", (meeting_ids,))


def _insert_session_groups(
    conn: object,
    detected_by_meeting: dict[int, list[SessionGroup]],
) -> tuple[int, int]:
    group_count = 0
    link_count = 0
    with conn.cursor() as cur:
        for groups in detected_by_meeting.values():
            for group in groups:
                cur.execute(
                    """
                    INSERT INTO session_groups (
                        meeting_id, questioner_mona_cd, respondents,
                        seq_start, seq_end, utterance_count, total_chars
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        group.meeting_id,
                        group.questioner_mona_cd,
                        Jsonb(
                            [
                                {"name": respondent.name, "title": respondent.title}
                                for respondent in group.respondents
                            ]
                        ),
                        group.seq_start,
                        group.seq_end,
                        group.utterance_count,
                        group.total_chars,
                    ),
                )
                session_group_id = cur.fetchone()[0]
                cur.execute(
                    """
                    UPDATE utterances
                    SET session_group_id = %s
                    WHERE meeting_id = %s
                      AND sequence BETWEEN %s AND %s
                    """,
                    (
                        session_group_id,
                        group.meeting_id,
                        group.seq_start,
                        group.seq_end,
                    ),
                )
                group_count += 1
                link_count += cur.rowcount
    return group_count, link_count
