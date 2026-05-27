"""utterances 적재."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .benchmark import BenchmarkResult, measure_workers
from .db import execute_many, get_conn
from .progress import ProgressReporter
from .scrape_minutes import (
    MinutesInfo,
    UtteranceDraft,
    fetch_minutes,
    match_member,
    normalize_speaker_name,
    parse_minutes,
)

DEFAULT_SCRAPE_BENCHMARK_OUTPUT = Path("docs/PARALLEL-BENCHMARK.md")
DEFAULT_RETRY_DELAYS = (1.0, 4.0, 16.0)
DEFAULT_SCRAPE_WORKER_LEVELS = (5,)
MEMBER_SPEAKER_TITLES = frozenset(
    {
        "의원",
        "위원",
        "의장",
        "부의장",
        "의장대리",
        "위원장",
        "부위원장",
        "위원장대리",
        "소위원장",
        "소위원장대리",
    }
)


@dataclass(frozen=True)
class IngestUtterancesResult:
    """회의록 본문 적재 결과."""

    meeting_count: int
    scraped_meeting_count: int
    utterance_count: int
    selected_worker_count: int
    scrape_error_count: int
    member_mapped_count: int
    sample_errors: tuple[str, ...]
    scrape_failures: tuple["ScrapeFailure", ...]


@dataclass(frozen=True)
class ScrapeFailure:
    """회의록 스크래핑 최종 실패."""

    mnts_id: int
    error: str
    attempts: int


@dataclass(frozen=True)
class _MeetingTarget:
    mnts_id: int
    conf_date: str
    meeting_type: str
    title: str


_UPSERT_UTTERANCES_SQL = """
    INSERT INTO utterances (
        meeting_id, sequence, speaker_name, speaker_title, speaker_mona_cd, content
    )
    VALUES (
        %(meeting_id)s, %(sequence)s, %(speaker_name)s, %(speaker_title)s,
        %(speaker_mona_cd)s, %(content)s
    )
    ON CONFLICT (meeting_id, sequence) DO UPDATE SET
        speaker_name    = EXCLUDED.speaker_name,
        speaker_title   = EXCLUDED.speaker_title,
        speaker_mona_cd = EXCLUDED.speaker_mona_cd,
        content         = EXCLUDED.content
"""


def ingest_utterances(
    *,
    calibration_limit: int = 500,
    meeting_ids: Sequence[int] | None = None,
    benchmark_sample_size: int = 100,
    worker_levels: tuple[int, ...] = DEFAULT_SCRAPE_WORKER_LEVELS,
    benchmark_output_path: Path = DEFAULT_SCRAPE_BENCHMARK_OUTPUT,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    allow_partial: bool = False,
) -> IngestUtterancesResult:
    """회의록 HTML을 스크래핑해 발언을 적재한다."""
    target_meetings = _load_target_meetings(
        calibration_limit=calibration_limit,
        meeting_ids=meeting_ids,
    )
    target_meeting_ids = [meeting.mnts_id for meeting in target_meetings]
    print(
        f"[ingest-utterances] target meetings={len(target_meeting_ids)}",
        flush=True,
    )
    benchmark = measure_workers(
        lambda meeting, worker_count: _scrape_one_with_retry(
            meeting,
            retry_delays=retry_delays,
        ),
        items=target_meetings[:benchmark_sample_size],
        levels=worker_levels,
    )
    _write_scrape_benchmark(benchmark, benchmark_output_path)
    _ensure_benchmark_acceptable(benchmark)

    scraped, errors = _scrape_meetings(
        target_meetings,
        worker_count=benchmark.selected_worker_count,
        retry_delays=retry_delays,
    )
    if errors:
        retried, errors = _retry_failed_meetings(
            errors,
            selected_worker_count=benchmark.selected_worker_count,
            retry_delays=retry_delays,
        )
        scraped.update(retried)
    member_map = _load_unique_member_name_map()
    utterance_rows = _normalize_utterance_rows(scraped, member_map)
    scraped_meeting_ids = sorted(scraped)

    with get_conn() as conn:
        _replace_utterances_for_meetings(conn, scraped_meeting_ids)
        upserted_utterances = execute_many(conn, _UPSERT_UTTERANCES_SQL, utterance_rows)
        conn.commit()

    result = IngestUtterancesResult(
        meeting_count=len(target_meeting_ids),
        scraped_meeting_count=len(scraped),
        utterance_count=upserted_utterances,
        selected_worker_count=benchmark.selected_worker_count,
        scrape_error_count=len(errors),
        member_mapped_count=sum(1 for row in utterance_rows if row["speaker_mona_cd"]),
        sample_errors=tuple(
            f"{error.mnts_id}: attempts={error.attempts} {error.error}"
            for error in errors[:5]
        ),
        scrape_failures=tuple(errors),
    )
    if errors and not allow_partial:
        sample = "; ".join(
            f"{error.mnts_id}: attempts={error.attempts} {error.error}"
            for error in errors[:5]
        )
        raise RuntimeError(
            "utterance ingest finished with persistent scrape failures: "
            f"errors={len(errors)} sample={sample}"
        )
    return result


def _load_target_meetings(
    *,
    calibration_limit: int,
    meeting_ids: Sequence[int] | None,
) -> list[_MeetingTarget]:
    if meeting_ids is not None:
        ids = list(meeting_ids)
        if not ids:
            return []
        return _load_meetings_by_ids(ids)
    if calibration_limit <= 0:
        raise ValueError("calibration_limit must be positive")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id, conf_date::text, meeting_type, title
            FROM meetings
            ORDER BY conf_date DESC, mnts_id DESC
            LIMIT %s
            """,
            (calibration_limit,),
        )
        return [
            _MeetingTarget(
                mnts_id=row[0],
                conf_date=row[1],
                meeting_type=row[2],
                title=row[3],
            )
            for row in cur.fetchall()
        ]


def _load_meetings_by_ids(meeting_ids: list[int]) -> list[_MeetingTarget]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT mnts_id, conf_date::text, meeting_type, title
            FROM meetings
            WHERE mnts_id = ANY(%s)
            ORDER BY array_position(%s::int[], mnts_id)
            """,
            (meeting_ids, meeting_ids),
        )
        rows = cur.fetchall()
    found_ids = {row[0] for row in rows}
    missing_ids = [meeting_id for meeting_id in meeting_ids if meeting_id not in found_ids]
    if missing_ids:
        raise ValueError(f"meetings not found: {missing_ids[:5]}")
    return [
        _MeetingTarget(
            mnts_id=row[0],
            conf_date=row[1],
            meeting_type=row[2],
            title=row[3],
        )
        for row in rows
    ]


def _scrape_one(meeting: _MeetingTarget) -> list[UtteranceDraft]:
    html, url = fetch_minutes(meeting.mnts_id)
    info, utterances = parse_minutes(html, meeting.mnts_id, url)
    _validate_minutes_info(info, meeting)
    if not utterances:
        raise RuntimeError(f"no utterances found for meeting {meeting.mnts_id}")
    return utterances


def _scrape_one_with_retry(
    meeting: _MeetingTarget,
    *,
    retry_delays: tuple[float, ...],
) -> list[UtteranceDraft]:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _scrape_one(meeting)
        except Exception as exc:
            if attempts > len(retry_delays):
                raise RuntimeError(f"after {attempts} attempts: {exc}") from exc
            delay = retry_delays[attempts - 1]
            print(
                f"[retry] minutes scraping id={meeting.mnts_id} "
                f"attempt={attempts} next_delay={delay:.1f}s error={exc}",
                flush=True,
            )
            time.sleep(delay)


def _scrape_meetings(
    meetings: list[_MeetingTarget],
    *,
    worker_count: int,
    retry_delays: tuple[float, ...],
    label: str = "minutes scraping",
) -> tuple[dict[int, list[UtteranceDraft]], list[ScrapeFailure]]:
    scraped: dict[int, list[UtteranceDraft]] = {}
    errors: list[ScrapeFailure] = []
    progress = ProgressReporter(label, len(meetings))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(_scrape_one_with_retry, meeting, retry_delays=retry_delays): meeting
            for meeting in meetings
        }
        for future in as_completed(futures):
            meeting = futures[future]
            try:
                scraped[meeting.mnts_id] = future.result()
                progress.advance()
            except Exception as exc:  # noqa: BLE001 - scraping boundary errors are measured
                errors.append(
                    ScrapeFailure(
                        mnts_id=meeting.mnts_id,
                        error=str(exc),
                        attempts=len(retry_delays) + 1,
                    )
                )
                progress.advance(errors=1)
    progress.finish()
    return scraped, errors


def _retry_failed_meetings(
    errors: list[ScrapeFailure],
    *,
    selected_worker_count: int,
    retry_delays: tuple[float, ...],
) -> tuple[dict[int, list[UtteranceDraft]], list[ScrapeFailure]]:
    failed_ids = [error.mnts_id for error in errors]
    failed_meetings = _load_meetings_by_ids(failed_ids)
    retry_worker_count = min(5, max(1, selected_worker_count))
    print(
        "[retry] minutes scraping final pass "
        f"meetings={len(failed_ids)} workers={retry_worker_count}",
        flush=True,
    )
    return _scrape_meetings(
        failed_meetings,
        worker_count=retry_worker_count,
        retry_delays=retry_delays,
        label="minutes scraping final retry",
    )


def _validate_minutes_info(info: MinutesInfo, meeting: _MeetingTarget) -> None:
    if info.date != meeting.conf_date:
        raise RuntimeError(
            "minutes metadata mismatch: "
            f"id={meeting.mnts_id} expected_date={meeting.conf_date} "
            f"actual_date={info.date} actual_title={info.title}"
        )
    if meeting.meeting_type == "본회의" and "본회의" not in info.title:
        raise RuntimeError(
            "minutes metadata mismatch: "
            f"id={meeting.mnts_id} expected_type=본회의 actual_title={info.title}"
        )


def _load_unique_member_name_map() -> dict[str, str]:
    names: dict[str, list[str]] = {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT hg_nm, mona_cd FROM members")
        for hg_nm, mona_cd in cur.fetchall():
            names.setdefault(normalize_speaker_name(hg_nm), []).append(mona_cd)
    return {
        name: codes[0]
        for name, codes in names.items()
        if len(set(codes)) == 1
    }


def _normalize_utterance_rows(
    scraped: dict[int, list[UtteranceDraft]],
    member_map: dict[str, str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for meeting_id in sorted(scraped):
        for utterance in scraped[meeting_id]:
            speaker_mona_cd = None
            if utterance.speaker_title in MEMBER_SPEAKER_TITLES:
                speaker_mona_cd = match_member(utterance.speaker_name, member_map)
            rows.append(
                {
                    "meeting_id": utterance.meeting_id,
                    "sequence": utterance.sequence,
                    "speaker_name": utterance.speaker_name,
                    "speaker_title": utterance.speaker_title,
                    "speaker_mona_cd": speaker_mona_cd,
                    "content": utterance.content,
                }
            )
    return rows


def _replace_utterances_for_meetings(conn: object, meeting_ids: list[int]) -> None:
    if not meeting_ids:
        return
    with conn.cursor() as cur:
        cur.execute("DELETE FROM utterances WHERE meeting_id = ANY(%s)", (meeting_ids,))


def _write_scrape_benchmark(result: BenchmarkResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = output_path.read_text() if output_path.exists() else "# Parallel Benchmark\n"
    start = "<!-- SCRAPE_BENCHMARK_START -->"
    end = "<!-- SCRAPE_BENCHMARK_END -->"
    section = f"{start}\n{_render_scrape_benchmark(result)}\n{end}\n"
    if start in existing and end in existing:
        before = existing.split(start, 1)[0].rstrip()
        after = existing.split(end, 1)[1].lstrip()
        output_path.write_text(f"{before}\n\n{section}\n{after}".rstrip() + "\n")
    else:
        output_path.write_text(existing.rstrip() + "\n\n" + section)


def _ensure_benchmark_acceptable(result: BenchmarkResult) -> None:
    selected = next(
        run
        for run in result.runs
        if run.worker_count == result.selected_worker_count
    )
    if selected.error_rate >= result.max_error_rate:
        raise RuntimeError(
            "scraping benchmark did not find an acceptable worker count: "
            f"selected={selected.worker_count} error_rate={selected.error_rate:.1%} "
            f"threshold=<{result.max_error_rate:.1%}"
        )


def _render_scrape_benchmark(result: BenchmarkResult) -> str:
    lines = [
        "## Scraping Stage",
        "",
        f"Measured at: `{result.measured_at}`",
        "",
        f"Selected worker count: `{result.selected_worker_count}`",
        "",
        "| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in result.runs:
        lines.append(
            f"| {run.worker_count} | {run.call_count} | {run.success_count} | "
            f"{run.error_count} | {run.error_rate:.1%} | {run.seconds:.2f} | "
            f"{run.calls_per_second:.2f} |"
        )
    if any(run.errors for run in result.runs):
        lines.extend(["", "### Sample Errors", ""])
        for run in result.runs:
            if run.errors:
                lines.append(f"- `{run.worker_count}` workers: {', '.join(run.errors)}")
    return "\n".join(lines)
