"""session_group 정확도 검증 아티팩트 생성."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .db import get_conn

DEFAULT_EVAL_DIR = Path("docs/session-group-eval")
DEFAULT_EVAL_REPORT = Path("docs/SESSION-GROUP-EVAL.md")
DEFAULT_MEETING_TYPES = ("상임위", "특별위", "국정감사", "국정조사", "인사청문회")
MIN_RECOMMENDED_MEETINGS_PER_TYPE = 5
SESSION_GROUP_STANDALONE_PRECISION_THRESHOLD = 0.90
SESSION_GROUP_STANDALONE_RECALL_THRESHOLD = 0.70
LABEL_CORRECT = "correct"
LABEL_INCORRECT = "incorrect"
LABEL_MISSING = "missing"
LABEL_PENDING = ""
LABEL_VALUES = frozenset({LABEL_CORRECT, LABEL_INCORRECT, LABEL_MISSING, LABEL_PENDING})

LABEL_FIELDNAMES = (
    "label",
    "meeting_id",
    "meeting_type",
    "conf_date",
    "title",
    "session_group_id",
    "questioner_sequence",
    "questioner_mona_cd",
    "questioner_name",
    "seq_start",
    "seq_end",
    "utterance_count",
    "respondents",
    "questioner_content",
    "notes",
)


@dataclass(frozen=True)
class EvalMeeting:
    """정확도 검증 대상 회의."""

    meeting_id: int
    meeting_type: str
    conf_date: str
    title: str
    group_count: int


@dataclass(frozen=True)
class EvalCandidate:
    """사람이 검토할 자동 session_group 후보."""

    label: str
    meeting_id: int
    meeting_type: str
    conf_date: str
    title: str
    session_group_id: int
    questioner_sequence: int
    questioner_mona_cd: str
    questioner_name: str
    seq_start: int
    seq_end: int
    utterance_count: int
    respondents: str
    questioner_content: str
    notes: str = ""

    def to_row(self) -> dict[str, object]:
        return {
            "label": self.label,
            "meeting_id": self.meeting_id,
            "meeting_type": self.meeting_type,
            "conf_date": self.conf_date,
            "title": self.title,
            "session_group_id": self.session_group_id,
            "questioner_sequence": self.questioner_sequence,
            "questioner_mona_cd": self.questioner_mona_cd,
            "questioner_name": self.questioner_name,
            "seq_start": self.seq_start,
            "seq_end": self.seq_end,
            "utterance_count": self.utterance_count,
            "respondents": self.respondents,
            "questioner_content": self.questioner_content,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SessionGroupTypeEvalResult:
    """회의 유형별 라벨 기반 precision/recall 결과."""

    meeting_type: str
    correct_count: int
    incorrect_count: int
    missing_count: int
    pending_count: int

    @property
    def reviewed_count(self) -> int:
        return self.correct_count + self.incorrect_count + self.missing_count

    @property
    def precision(self) -> float | None:
        denominator = self.correct_count + self.incorrect_count
        if denominator == 0:
            return None
        return self.correct_count / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.correct_count + self.missing_count
        if denominator == 0:
            return None
        return self.correct_count / denominator

    @property
    def is_complete(self) -> bool:
        return self.pending_count == 0 and self.reviewed_count > 0


@dataclass(frozen=True)
class SessionGroupEvalResult:
    """라벨 기반 precision/recall 결과."""

    correct_count: int
    incorrect_count: int
    missing_count: int
    pending_count: int
    agent_labeled_count: int = 0
    human_labeled_count: int = 0
    by_type: tuple[SessionGroupTypeEvalResult, ...] = ()

    @property
    def reviewed_count(self) -> int:
        return self.correct_count + self.incorrect_count + self.missing_count

    @property
    def precision(self) -> float | None:
        denominator = self.correct_count + self.incorrect_count
        if denominator == 0:
            return None
        return self.correct_count / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.correct_count + self.missing_count
        if denominator == 0:
            return None
        return self.correct_count / denominator

    @property
    def is_complete(self) -> bool:
        return self.pending_count == 0 and self.reviewed_count > 0


def generate_session_group_eval(
    *,
    output_dir: Path = DEFAULT_EVAL_DIR,
    report_path: Path = DEFAULT_EVAL_REPORT,
    per_type: int = 5,
    min_groups: int = 5,
    max_groups: int = 80,
    overwrite: bool = False,
) -> SessionGroupEvalResult:
    """샘플·라벨 CSV와 평가 리포트를 생성한다."""
    meetings = select_eval_meetings(
        per_type=per_type,
        min_groups=min_groups,
        max_groups=max_groups,
    )
    candidates = load_eval_candidates([meeting.meeting_id for meeting in meetings])

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_meetings(output_dir / "meetings.csv", meetings)
    labels_path = output_dir / "labels.csv"
    if overwrite or not labels_path.exists():
        _write_labels(labels_path, candidates)

    result = evaluate_labels(labels_path)
    render_eval_report(
        result=result,
        meetings=meetings,
        labels_path=labels_path,
        output_path=report_path,
    )
    return result


def select_eval_meetings(
    *,
    per_type: int,
    min_groups: int,
    max_groups: int,
    meeting_types: Sequence[str] = DEFAULT_MEETING_TYPES,
) -> list[EvalMeeting]:
    """회의 유형별로 사람이 검토 가능한 규모의 최신 회의를 고른다."""
    if per_type <= 0:
        raise ValueError("per_type must be positive")
    if min_groups <= 0 or max_groups < min_groups:
        raise ValueError("group bounds are invalid")

    meetings: list[EvalMeeting] = []
    with get_conn() as conn, conn.cursor() as cur:
        for meeting_type in meeting_types:
            cur.execute(
                """
                WITH group_counts AS (
                    SELECT meeting_id, COUNT(*) AS group_count
                    FROM session_groups
                    GROUP BY meeting_id
                )
                SELECT m.mnts_id, m.meeting_type, m.conf_date::text, m.title, gc.group_count
                FROM meetings m
                JOIN group_counts gc ON gc.meeting_id = m.mnts_id
                WHERE m.meeting_type = %s
                  AND gc.group_count BETWEEN %s AND %s
                ORDER BY m.conf_date DESC, m.mnts_id DESC
                LIMIT %s
                """,
                (meeting_type, min_groups, max_groups, per_type),
            )
            rows = cur.fetchall()
            meetings.extend(
                EvalMeeting(
                    meeting_id=row[0],
                    meeting_type=row[1],
                    conf_date=row[2],
                    title=row[3],
                    group_count=row[4],
                )
                for row in rows
            )
    return meetings


def load_eval_candidates(meeting_ids: Sequence[int]) -> list[EvalCandidate]:
    """선택된 회의의 자동 session_group 후보를 라벨링 행으로 만든다."""
    if not meeting_ids:
        return []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH first_questioner AS (
                SELECT sg.id AS session_group_id, MIN(u.sequence) AS questioner_sequence
                FROM session_groups sg
                JOIN utterances u
                  ON u.meeting_id = sg.meeting_id
                 AND u.sequence BETWEEN sg.seq_start AND sg.seq_end
                 AND u.speaker_mona_cd = sg.questioner_mona_cd
                WHERE sg.meeting_id = ANY(%s)
                GROUP BY sg.id
            )
            SELECT
                m.mnts_id,
                m.meeting_type,
                m.conf_date::text,
                m.title,
                sg.id,
                fq.questioner_sequence,
                sg.questioner_mona_cd,
                mem.hg_nm,
                sg.seq_start,
                sg.seq_end,
                sg.utterance_count,
                sg.respondents::text,
                left(regexp_replace(u.content, E'[\\n\\r\\t]+', ' ', 'g'), 240)
                    AS questioner_content
            FROM session_groups sg
            JOIN meetings m ON m.mnts_id = sg.meeting_id
            JOIN members mem ON mem.mona_cd = sg.questioner_mona_cd
            JOIN first_questioner fq ON fq.session_group_id = sg.id
            JOIN utterances u
              ON u.meeting_id = sg.meeting_id
             AND u.sequence = fq.questioner_sequence
            WHERE sg.meeting_id = ANY(%s)
            ORDER BY m.meeting_type, m.conf_date DESC, m.mnts_id DESC, sg.seq_start
            """,
            (list(meeting_ids), list(meeting_ids)),
        )
        rows = cur.fetchall()

    return [
        EvalCandidate(
            label=LABEL_PENDING,
            meeting_id=row[0],
            meeting_type=row[1],
            conf_date=row[2],
            title=row[3],
            session_group_id=row[4],
            questioner_sequence=row[5],
            questioner_mona_cd=row[6],
            questioner_name=row[7],
            seq_start=row[8],
            seq_end=row[9],
            utterance_count=row[10],
            respondents=row[11],
            questioner_content=row[12],
        )
        for row in rows
    ]


def evaluate_labels(labels_path: Path) -> SessionGroupEvalResult:
    """라벨 CSV의 `label` 값으로 precision/recall 입력값을 계산한다."""
    rows = _read_label_rows(labels_path)
    return evaluate_label_rows(rows)


def evaluate_label_rows(rows: Sequence[Mapping[str, str]]) -> SessionGroupEvalResult:
    counts: dict[str, dict[str, int]] = {}
    agent_labeled = 0
    human_labeled = 0
    invalid_labels: set[str] = set()

    for row in rows:
        label = _normalize_label(row.get("label", ""))
        if label not in LABEL_VALUES:
            invalid_labels.add(label)
            continue
        meeting_type = str(row.get("meeting_type") or "unknown")
        bucket = counts.setdefault(
            meeting_type,
            {"correct": 0, "incorrect": 0, "missing": 0, "pending": 0},
        )
        if label == LABEL_CORRECT:
            bucket["correct"] += 1
            if _is_agent_reviewed(row):
                agent_labeled += 1
            else:
                human_labeled += 1
        elif label == LABEL_INCORRECT:
            bucket["incorrect"] += 1
            if _is_agent_reviewed(row):
                agent_labeled += 1
            else:
                human_labeled += 1
        elif label == LABEL_MISSING:
            bucket["missing"] += 1
            if _is_agent_reviewed(row):
                agent_labeled += 1
            else:
                human_labeled += 1
        else:
            bucket["pending"] += 1

    if invalid_labels:
        raise ValueError(f"invalid labels: {sorted(invalid_labels)}")

    by_type = tuple(
        SessionGroupTypeEvalResult(
            meeting_type=meeting_type,
            correct_count=values["correct"],
            incorrect_count=values["incorrect"],
            missing_count=values["missing"],
            pending_count=values["pending"],
        )
        for meeting_type, values in sorted(counts.items())
    )
    return SessionGroupEvalResult(
        correct_count=sum(row.correct_count for row in by_type),
        incorrect_count=sum(row.incorrect_count for row in by_type),
        missing_count=sum(row.missing_count for row in by_type),
        pending_count=sum(row.pending_count for row in by_type),
        agent_labeled_count=agent_labeled,
        human_labeled_count=human_labeled,
        by_type=by_type,
    )


def render_eval_report(
    *,
    result: SessionGroupEvalResult,
    meetings: Sequence[EvalMeeting],
    labels_path: Path,
    output_path: Path,
) -> None:
    """정확도 검증 리포트를 Markdown으로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(result, meetings, labels_path))


def _write_meetings(path: Path, meetings: Sequence[EvalMeeting]) -> None:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=("meeting_id", "meeting_type", "conf_date", "title", "group_count"),
            lineterminator="\n",
        )
        writer.writeheader()
        for meeting in meetings:
            writer.writerow(
                {
                    "meeting_id": meeting.meeting_id,
                    "meeting_type": meeting.meeting_type,
                    "conf_date": meeting.conf_date,
                    "title": meeting.title,
                    "group_count": meeting.group_count,
                }
            )


def _write_labels(path: Path, candidates: Sequence[EvalCandidate]) -> None:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=LABEL_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.to_row())


def _read_label_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def _normalize_label(value: str) -> str:
    return str(value or "").strip().lower()


def _is_agent_reviewed(row: Mapping[str, str]) -> bool:
    notes = str(row.get("notes") or "").lower()
    return any(
        marker in notes
        for marker in ("agent-first-pass", "agent-reviewed", "codex-reviewed")
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "pending"
    return f"{value * 100:.1f}%"


def _needs_utterance_fallback(row: SessionGroupTypeEvalResult) -> bool:
    return (
        row.precision is None
        or row.recall is None
        or row.precision < SESSION_GROUP_STANDALONE_PRECISION_THRESHOLD
        or row.recall < SESSION_GROUP_STANDALONE_RECALL_THRESHOLD
    )


def _render_markdown(
    result: SessionGroupEvalResult,
    meetings: Sequence[EvalMeeting],
    labels_path: Path,
) -> str:
    if result.is_complete and result.agent_labeled_count:
        status = "complete Codex-reviewed"
    elif result.is_complete:
        status = "complete human-reviewed"
    else:
        status = "pending labeled review"
    fallback_types = [
        f"{row.meeting_type}(P={_pct(row.precision)}, R={_pct(row.recall)})"
        for row in result.by_type
        if _needs_utterance_fallback(row)
    ]
    lines = [
        "# Session Group Evaluation",
        "",
        "This report measures Q&A `session_group` semantic accuracy on sampled",
        "meetings. The CSV label file is the review surface; the code calculates",
        "metrics after a reviewer or agent marks labels.",
        "",
        "## Status",
        "",
        f"- Labeled review status: {status}",
        f"- Label file: `{labels_path}`",
        f"- Pending auto candidates: {result.pending_count}",
        f"- Agent-reviewed labels: {result.agent_labeled_count}",
        f"- Human-reviewed labels: {result.human_labeled_count}",
        "- Standalone-use threshold: "
        f"precision >= {_pct(SESSION_GROUP_STANDALONE_PRECISION_THRESHOLD)}, "
        f"recall >= {_pct(SESSION_GROUP_STANDALONE_RECALL_THRESHOLD)}",
        "- Types requiring `utterances` sequence-window fallback: "
        + (", ".join(fallback_types) if fallback_types else "None"),
        "",
        "## Metrics",
        "",
        f"- Correct auto groups: {result.correct_count}",
        f"- Incorrect auto groups: {result.incorrect_count}",
        f"- Missing expected groups: {result.missing_count}",
        f"- Precision: {_pct(result.precision)}",
        f"- Recall: {_pct(result.recall)}",
        "",
        "## Metrics By Meeting Type",
        "",
        "| Type | Correct | Incorrect | Missing | Pending | Precision | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result.by_type:
        lines.append(
            f"| {row.meeting_type} | {row.correct_count} | {row.incorrect_count} | "
            f"{row.missing_count} | {row.pending_count} | {_pct(row.precision)} | "
            f"{_pct(row.recall)} |"
        )

    sampled_counts = {
        meeting_type: sum(1 for meeting in meetings if meeting.meeting_type == meeting_type)
        for meeting_type in DEFAULT_MEETING_TYPES
    }
    missing_types = [
        meeting_type
        for meeting_type, count in sampled_counts.items()
        if count == 0
    ]
    undersampled_types = [
        f"{meeting_type}({count})"
        for meeting_type, count in sampled_counts.items()
        if 0 < count < MIN_RECOMMENDED_MEETINGS_PER_TYPE
    ]
    lines.extend(
        [
            "",
            "## Coverage Notes",
            "",
            f"- Expected meeting types: {', '.join(DEFAULT_MEETING_TYPES)}",
            "- Types without sampled meetings: "
            + (", ".join(missing_types) if missing_types else "None"),
            "- Types below recommended sample count: "
            + (", ".join(undersampled_types) if undersampled_types else "None"),
            "",
            "## Labeling Guide",
            "",
            "- Mark an auto-generated row `correct` if the questioner and start point form a real Q&A meaning unit.",
            "- Mark it `incorrect` if it is a procedural/noisy group rather than a Q&A meaning unit.",
            "- Add a new row with `missing` if the meeting has a real Q&A group that automation missed.",
            "- Leave `label` blank for rows not yet reviewed. Human review is only needed for disputed examples.",
            "",
            "## Sampled Meetings",
            "",
            "| Type | Meeting ID | Date | Groups | Title |",
            "|---|---:|---|---:|---|",
        ]
    )
    for meeting in meetings:
        lines.append(
            f"| {meeting.meeting_type} | {meeting.meeting_id} | {meeting.conf_date} | "
            f"{meeting.group_count} | {meeting.title} |"
        )
    lines.append("")
    return "\n".join(lines)
