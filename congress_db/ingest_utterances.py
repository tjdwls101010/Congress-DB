"""utterances 적재."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Sequence

from .benchmark import BenchmarkResult, WorkerRun, representative_sample
from .db import execute_many, get_conn
from .progress import ProgressReporter, safe_print
from .scrape_minutes import (
    MinutesInfo,
    UtteranceDraft,
    fetch_minutes,
    match_member,
    normalize_speaker_name,
    parse_minutes,
)
from .utterance_mapping_quality import MEMBER_SPEAKER_TITLES

DEFAULT_SCRAPE_BENCHMARK_OUTPUT = Path("docs/ops/PARALLEL-BENCHMARK.md")
DEFAULT_RETRY_DELAYS = (1.0, 4.0, 16.0)
DEFAULT_SCRAPE_WORKER_LEVELS = (2, 5, 10, 20, 40)
SCRAPE_MAX_ERROR_RATE = 0.01
SCRAPE_MAX_RETRY_RATE = 0.05
SCRAPE_MIN_THROUGHPUT_RATIO = 0.95
KNOWN_HTML_UNAVAILABLE_MNTS_IDS = frozenset({52354, 52713})


@dataclass(frozen=True)
class IngestUtterancesResult:
    """회의록 본문 적재 결과."""

    meeting_count: int
    scraped_meeting_count: int
    scraped_meeting_ids: tuple[int, ...]
    utterance_count: int
    selected_worker_count: int
    retry_count: int
    retried_meeting_count: int
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


@dataclass
class _RetryTelemetry:
    retry_count: int = 0
    retried_meeting_ids: set[int] = field(default_factory=set)
    samples: list[str] = field(default_factory=list)
    lock: Any = field(default_factory=Lock, repr=False)

    def record(self, *, mnts_id: int, error: str) -> None:
        with self.lock:
            self.retry_count += 1
            self.retried_meeting_ids.add(mnts_id)
            if len(self.samples) < 5:
                self.samples.append(f"{mnts_id}: {error}")

    def record_final_retry(self, *, mnts_id: int) -> None:
        with self.lock:
            self.retry_count += 1
            self.retried_meeting_ids.add(mnts_id)
            if len(self.samples) < 5:
                self.samples.append(f"{mnts_id}: final retry pass")


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
    scrape_worker_count: int | None = None,
) -> IngestUtterancesResult:
    """회의록 HTML을 스크래핑해 발언을 적재한다."""
    target_meetings = _load_target_meetings(
        calibration_limit=calibration_limit,
        meeting_ids=meeting_ids,
    )
    target_meeting_ids = [meeting.mnts_id for meeting in target_meetings]
    safe_print(
        f"[ingest-utterances] target meetings={len(target_meeting_ids)}",
        flush=True,
    )
    if scrape_worker_count is None:
        benchmark = _benchmark_scrape_workers(
            representative_sample(target_meetings, benchmark_sample_size),
            levels=worker_levels,
            retry_delays=retry_delays,
        )
        _write_scrape_benchmark(benchmark, benchmark_output_path)
        _ensure_benchmark_acceptable(benchmark)
        selected_worker_count = benchmark.selected_worker_count
    else:
        selected_worker_count = scrape_worker_count

    scraped, errors, scrape_telemetry = _scrape_meetings(
        target_meetings,
        worker_count=selected_worker_count,
        retry_delays=retry_delays,
    )
    retry_count = scrape_telemetry.retry_count
    retried_meeting_ids = set(scrape_telemetry.retried_meeting_ids)
    if errors:
        retried, errors, final_retry_telemetry = _retry_failed_meetings(
            errors,
            selected_worker_count=selected_worker_count,
            retry_delays=retry_delays,
        )
        scraped.update(retried)
        retry_count += final_retry_telemetry.retry_count
        retried_meeting_ids.update(final_retry_telemetry.retried_meeting_ids)
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
        scraped_meeting_ids=tuple(scraped_meeting_ids),
        utterance_count=upserted_utterances,
        selected_worker_count=selected_worker_count,
        retry_count=retry_count,
        retried_meeting_count=len(retried_meeting_ids),
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
    retry_telemetry: _RetryTelemetry | None = None,
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
            if retry_telemetry is not None:
                retry_telemetry.record(mnts_id=meeting.mnts_id, error=str(exc))
            safe_print(
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
) -> tuple[dict[int, list[UtteranceDraft]], list[ScrapeFailure], _RetryTelemetry]:
    scraped: dict[int, list[UtteranceDraft]] = {}
    errors: list[ScrapeFailure] = []
    telemetry = _RetryTelemetry()
    progress = ProgressReporter(label, len(meetings))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _scrape_one_with_retry,
                meeting,
                retry_delays=retry_delays,
                retry_telemetry=telemetry,
            ): meeting
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
    return scraped, errors, telemetry


def _retry_failed_meetings(
    errors: list[ScrapeFailure],
    *,
    selected_worker_count: int,
    retry_delays: tuple[float, ...],
) -> tuple[dict[int, list[UtteranceDraft]], list[ScrapeFailure], _RetryTelemetry]:
    failed_ids = [error.mnts_id for error in errors]
    failed_meetings = _load_meetings_by_ids(failed_ids)
    retry_worker_count = min(5, max(1, selected_worker_count))
    safe_print(
        "[retry] minutes scraping final pass "
        f"meetings={len(failed_ids)} workers={retry_worker_count}",
        flush=True,
    )
    retried, remaining_errors, telemetry = _scrape_meetings(
        failed_meetings,
        worker_count=retry_worker_count,
        retry_delays=retry_delays,
        label="minutes scraping final retry",
    )
    for failed_id in failed_ids:
        telemetry.record_final_retry(mnts_id=failed_id)
    return retried, remaining_errors, telemetry


def _benchmark_scrape_workers(
    meetings: Sequence[_MeetingTarget],
    *,
    levels: tuple[int, ...],
    retry_delays: tuple[float, ...],
) -> BenchmarkResult:
    """회의록 스크래핑 benchmark는 최종 실패뿐 아니라 retry storm도 탈락 신호로 본다."""
    sample = list(meetings)
    overall = ProgressReporter("worker benchmark", len(levels), step=1)
    overall.start()
    runs: list[WorkerRun] = []
    for worker in levels:
        run = _measure_scrape_worker(
            sample,
            worker_count=worker,
            retry_delays=retry_delays,
        )
        runs.append(run)
        overall.advance()
        if (
            any(
                _is_scrape_run_acceptable(
                    measured,
                    max_error_rate=SCRAPE_MAX_ERROR_RATE,
                    max_retry_rate=SCRAPE_MAX_RETRY_RATE,
                )
                for measured in runs
            )
            and not _is_scrape_run_acceptable(
                run,
                max_error_rate=SCRAPE_MAX_ERROR_RATE,
                max_retry_rate=SCRAPE_MAX_RETRY_RATE,
            )
        ):
            break
    overall.finish()
    selected = _select_scrape_worker(
        runs,
        max_error_rate=SCRAPE_MAX_ERROR_RATE,
        max_retry_rate=SCRAPE_MAX_RETRY_RATE,
        min_throughput_ratio=SCRAPE_MIN_THROUGHPUT_RATIO,
    )
    return BenchmarkResult(
        measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        runs=tuple(runs),
        selected_worker_count=selected.worker_count,
        max_error_rate=SCRAPE_MAX_ERROR_RATE,
        min_throughput_ratio=SCRAPE_MIN_THROUGHPUT_RATIO,
    )


def _measure_scrape_worker(
    meetings: Sequence[_MeetingTarget],
    *,
    worker_count: int,
    retry_delays: tuple[float, ...],
) -> WorkerRun:
    telemetry = _RetryTelemetry()
    start = time.perf_counter()
    success_count = 0
    errors: list[str] = []
    progress = ProgressReporter(f"benchmark workers={worker_count}", len(meetings))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(
                _scrape_one_with_retry,
                meeting,
                retry_delays=retry_delays,
                retry_telemetry=telemetry,
            )
            for meeting in meetings
        ]
        for future in as_completed(futures):
            try:
                future.result()
                success_count += 1
                progress.advance()
            except Exception as exc:  # noqa: BLE001 - benchmark records boundary failures
                if len(errors) < 5:
                    errors.append(str(exc))
                progress.advance(errors=1)
    progress.finish()

    seconds = time.perf_counter() - start
    call_count = len(meetings)
    return WorkerRun(
        worker_count=worker_count,
        call_count=call_count,
        success_count=success_count,
        error_count=call_count - success_count,
        seconds=seconds,
        errors=tuple(errors),
        retry_count=telemetry.retry_count,
        retry_item_count=len(telemetry.retried_meeting_ids),
        retry_samples=tuple(telemetry.samples),
    )


def _select_scrape_worker(
    runs: Sequence[WorkerRun],
    *,
    max_error_rate: float,
    max_retry_rate: float,
    min_throughput_ratio: float,
) -> WorkerRun:
    acceptable = [
        run
        for run in runs
        if _is_scrape_run_acceptable(
            run,
            max_error_rate=max_error_rate,
            max_retry_rate=max_retry_rate,
        )
    ]
    if acceptable:
        best_throughput = max(run.calls_per_second for run in acceptable)
        near_best = [
            run
            for run in acceptable
            if run.calls_per_second >= best_throughput * min_throughput_ratio
        ]
        return min(near_best, key=lambda run: run.worker_count)
    return min(runs, key=lambda run: (run.error_rate, run.retry_rate, -run.calls_per_second))


def _is_scrape_run_acceptable(
    run: WorkerRun,
    *,
    max_error_rate: float,
    max_retry_rate: float,
) -> bool:
    return run.error_rate < max_error_rate and run.retry_rate <= max_retry_rate


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
    if selected.retry_rate > SCRAPE_MAX_RETRY_RATE:
        raise RuntimeError(
            "scraping benchmark did not find a stable worker count: "
            f"selected={selected.worker_count} retry_rate={selected.retry_rate:.1%} "
            f"threshold<={SCRAPE_MAX_RETRY_RATE:.1%}"
        )


def _render_scrape_benchmark(result: BenchmarkResult) -> str:
    lines = [
        "## Scraping Stage",
        "",
        f"Measured at: `{result.measured_at}`",
        "",
        f"Selected worker count: `{result.selected_worker_count}`",
        "",
        "Selection policy: choose the lowest worker count that stays under the "
        f"{result.max_error_rate:.0%} final-error threshold, keeps retried meetings "
        f"at or below {SCRAPE_MAX_RETRY_RATE:.0%}, and reaches at least "
        f"{result.min_throughput_ratio:.0%} of the best stable throughput.",
        "",
        "| Workers | Calls | Success | Errors | Error rate | Retried meetings | Retry rate | Retry attempts | Seconds | Calls/sec |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in result.runs:
        lines.append(
            f"| {run.worker_count} | {run.call_count} | {run.success_count} | "
            f"{run.error_count} | {run.error_rate:.1%} | "
            f"{run.retry_item_count} | {run.retry_rate:.1%} | {run.retry_count} | "
            f"{run.seconds:.2f} | "
            f"{run.calls_per_second:.2f} |"
        )
    if any(run.errors for run in result.runs):
        lines.extend(["", "### Sample Errors", ""])
        for run in result.runs:
            if run.errors:
                lines.append(f"- `{run.worker_count}` workers: {', '.join(run.errors)}")
    if any(run.retry_samples for run in result.runs):
        lines.extend(["", "### Sample Retries", ""])
        for run in result.runs:
            if run.retry_samples:
                lines.append(f"- `{run.worker_count}` workers: {', '.join(run.retry_samples)}")
    return "\n".join(lines)
