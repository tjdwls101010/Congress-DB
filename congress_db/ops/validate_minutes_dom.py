"""회의록 DOM 구조 샘플 검증."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..core.db import get_conn
from ..core.progress import ProgressReporter
from ..ingest.scrape_minutes import MinutesDomProfile, fetch_minutes, inspect_minutes_dom

DEFAULT_DOM_VALIDATION_OUTPUT = Path("docs/ops/MINUTES-DOM-VALIDATION.md")
DEFAULT_VALIDATION_RETRY_DELAYS = (1.0, 4.0, 16.0)


@dataclass(frozen=True)
class MeetingSample:
    """DOM 검증 대상 회의."""

    mnts_id: int
    meeting_type: str
    conf_date: str
    title: str
    sample_layer: str


@dataclass(frozen=True)
class DomValidationRow:
    """회의 1건의 DOM 검증 결과."""

    sample: MeetingSample
    profile: MinutesDomProfile | None
    error: str | None = None


@dataclass(frozen=True)
class DomValidationResult:
    """DOM 샘플 검증 집계."""

    rows: tuple[DomValidationRow, ...]

    @property
    def checked_count(self) -> int:
        return len(self.rows)

    @property
    def error_count(self) -> int:
        return sum(1 for row in self.rows if row.error)

    @property
    def parse_failure_count(self) -> int:
        return sum(
            1
            for row in self.rows
            if row.profile is not None and row.profile.utterance_count == 0
        )


def validate_minutes_dom(
    *,
    meeting_ids: Sequence[int] | None = None,
    per_type: int = 10,
    output_path: Path = DEFAULT_DOM_VALIDATION_OUTPUT,
    retry_delays: tuple[float, ...] = DEFAULT_VALIDATION_RETRY_DELAYS,
) -> DomValidationResult:
    """회의 유형별 다층 샘플의 DOM 구조를 검증하고 Markdown으로 남긴다."""
    samples = _load_samples(meeting_ids=meeting_ids, per_type=per_type)
    progress = ProgressReporter("minutes DOM validation", len(samples))
    progress.start()
    rows: list[DomValidationRow] = []
    for sample in samples:
        try:
            profile = _inspect_with_retry(sample.mnts_id, retry_delays=retry_delays)
            rows.append(DomValidationRow(sample=sample, profile=profile))
            progress.advance(errors=1 if profile.utterance_count == 0 else 0)
        except Exception as exc:  # noqa: BLE001 - validation records boundary failures
            rows.append(DomValidationRow(sample=sample, profile=None, error=str(exc)))
            progress.advance(errors=1)
    progress.finish()

    result = DomValidationResult(rows=tuple(rows))
    render_dom_validation_report(result, output_path)
    return result


def _inspect_with_retry(
    mnts_id: int,
    *,
    retry_delays: tuple[float, ...],
) -> MinutesDomProfile:
    attempts = 0
    while True:
        attempts += 1
        try:
            html, _ = fetch_minutes(mnts_id)
            return inspect_minutes_dom(html, mnts_id)
        except Exception as exc:
            if attempts > len(retry_delays):
                raise
            delay = retry_delays[attempts - 1]
            print(
                f"[retry] minutes DOM validation id={mnts_id} "
                f"attempt={attempts} next_delay={delay:.1f}s error={exc}",
                flush=True,
            )
            time.sleep(delay)


def render_dom_validation_report(result: DomValidationResult, output_path: Path) -> None:
    """DOM 검증 결과를 Markdown 문서로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(result))


def _load_samples(
    *,
    meeting_ids: Sequence[int] | None,
    per_type: int,
) -> list[MeetingSample]:
    if meeting_ids is not None:
        return _load_explicit_samples(meeting_ids)
    if per_type <= 0:
        raise ValueError("per_type must be positive")
    return _load_stratified_samples(per_type)


def _load_explicit_samples(meeting_ids: Sequence[int]) -> list[MeetingSample]:
    ids = list(meeting_ids)
    if not ids:
        return []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id, meeting_type, conf_date::text, title
            FROM meetings
            WHERE mnts_id = ANY(%s)
            ORDER BY conf_date DESC, mnts_id DESC
            """,
            (ids,),
        )
        return [
            MeetingSample(
                mnts_id=row[0],
                meeting_type=row[1],
                conf_date=row[2],
                title=row[3],
                sample_layer="explicit",
            )
            for row in cur.fetchall()
        ]


def _load_stratified_samples(per_type: int) -> list[MeetingSample]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH ranked AS (
                SELECT
                    mnts_id,
                    meeting_type,
                    conf_date::text AS conf_date,
                    title,
                    row_number() OVER (
                        PARTITION BY meeting_type
                        ORDER BY conf_date DESC, mnts_id DESC
                    ) AS recent_rank,
                    row_number() OVER (
                        PARTITION BY meeting_type
                        ORDER BY conf_date ASC, mnts_id ASC
                    ) AS old_rank
                FROM meetings
            )
            SELECT mnts_id, meeting_type, conf_date, title, 'recent' AS sample_layer
            FROM ranked
            WHERE recent_rank <= %s
            UNION
            SELECT mnts_id, meeting_type, conf_date, title, 'old' AS sample_layer
            FROM ranked
            WHERE old_rank <= %s
            ORDER BY meeting_type, sample_layer, conf_date DESC, mnts_id DESC
            """,
            (per_type, max(1, per_type // 3)),
        )
        return [
            MeetingSample(
                mnts_id=row[0],
                meeting_type=row[1],
                conf_date=row[2],
                title=row[3],
                sample_layer=row[4],
            )
            for row in cur.fetchall()
        ]


def _render_markdown(result: DomValidationResult) -> str:
    lines = [
        "# Minutes DOM Validation",
        "",
        "This report validates the actual `record.assembly.go.kr` meeting-minutes DOM",
        "across meeting types before bulk utterance scraping.",
        "",
        "## Summary",
        "",
        f"- Checked meetings: {result.checked_count}",
        f"- Fetch/HTTP errors: {result.error_count}",
        f"- Parse failures (0 utterances): {result.parse_failure_count}",
        "",
        "## By Meeting Type",
        "",
        "| Type | Checked | Errors | Parse failures | Min utterances | Max utterances |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for meeting_type in sorted({row.sample.meeting_type for row in result.rows}):
        rows = [row for row in result.rows if row.sample.meeting_type == meeting_type]
        profiles = [row.profile for row in rows if row.profile is not None]
        counts = [profile.utterance_count for profile in profiles]
        lines.append(
            f"| {meeting_type} | {len(rows)} | "
            f"{sum(1 for row in rows if row.error)} | "
            f"{sum(1 for profile in profiles if profile.utterance_count == 0)} | "
            f"{min(counts) if counts else 0} | {max(counts) if counts else 0} |"
        )

    lines.extend(
        [
            "",
            "## Sample Details",
            "",
            "| mnts_id | Layer | Type | Date | Speakers | Names | Titles | Talk txt | spk_sub | Utterances | First speaker class | Error |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in result.rows:
        profile = row.profile
        error = (row.error or "").replace("|", "\\|")
        lines.append(
            f"| {row.sample.mnts_id} | {row.sample.sample_layer} | "
            f"{row.sample.meeting_type} | {row.sample.conf_date} | "
            f"{profile.speaker_count if profile else 0} | "
            f"{profile.data_name_count if profile else 0} | "
            f"{profile.data_pos_count if profile else 0} | "
            f"{profile.talk_txt_count if profile else 0} | "
            f"{profile.spk_sub_speaker_count if profile else 0} | "
            f"{profile.utterance_count if profile else 0} | "
            f"`{profile.first_speaker_class if profile and profile.first_speaker_class else ''}` | "
            f"{error} |"
        )
    lines.append("")
    return "\n".join(lines)
