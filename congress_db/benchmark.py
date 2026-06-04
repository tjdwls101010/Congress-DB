"""병렬 API 워커 측정.

deep module: 호출자는 `measure_workers()`로 워커 후보를 실측하고,
`render_parallel_benchmark()`로 사람이 읽을 문서를 남기면 된다.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from .progress import ProgressReporter

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_WORKER_LEVELS = (5, 20, 50, 100, 200)


@dataclass(frozen=True)
class WorkerRun:
    """단일 worker count 측정 결과."""

    worker_count: int
    call_count: int
    success_count: int
    error_count: int
    seconds: float
    errors: tuple[str, ...] = ()
    retry_count: int = 0
    retry_item_count: int = 0
    retry_samples: tuple[str, ...] = ()

    @property
    def error_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count

    @property
    def retry_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.retry_item_count / self.call_count

    @property
    def calls_per_second(self) -> float:
        if self.seconds <= 0:
            return 0.0
        return self.call_count / self.seconds


@dataclass(frozen=True)
class BenchmarkResult:
    """여러 worker count 측정 결과와 자동 선정값."""

    measured_at: str
    runs: tuple[WorkerRun, ...]
    selected_worker_count: int
    max_error_rate: float
    min_throughput_ratio: float
    max_retry_rate: float | None = None


def measure_workers(
    api_callable: Callable[[T, int], R],
    *,
    n: int = 100,
    items: Sequence[T] | None = None,
    levels: Sequence[int] = DEFAULT_WORKER_LEVELS,
    max_error_rate: float = 0.01,
    max_retry_rate: float | None = None,
    min_throughput_ratio: float = 0.95,
    retry_count_from_result: Callable[[R], int] | None = None,
    stop_after_unacceptable_after_acceptance: bool = False,
) -> BenchmarkResult:
    """worker 후보별로 같은 `items`를 호출하고 안정적인 후보를 고른다.

    `api_callable`은 `(item, worker_count)`를 받는다. worker_count를 넘기는 이유는
    테스트와 운영 문서에서 어떤 워커가 어떤 실패를 냈는지 추적하기 위함이다.

    선택 정책은 보수적이다. rate limit이 알려지지 않은 외부 API를 다루므로,
    에러율 기준을 통과한 후보 중 최고 처리량의 `min_throughput_ratio` 이상을 내는
    가장 낮은 worker count를 고른다.
    """
    sample = list(items if items is not None else range(n))  # type: ignore[arg-type]
    overall = ProgressReporter(
        "worker benchmark",
        len(levels),
        step=1,
    )
    overall.start()
    runs_list: list[WorkerRun] = []
    for worker in levels:
        run = _measure_one(
            api_callable,
            sample,
            worker,
            retry_count_from_result=retry_count_from_result,
        )
        runs_list.append(run)
        overall.advance()
        if (
            stop_after_unacceptable_after_acceptance
            and any(_is_run_acceptable(measured, max_error_rate, max_retry_rate) for measured in runs_list)
            and not _is_run_acceptable(run, max_error_rate, max_retry_rate)
        ):
            break
    runs = tuple(runs_list)
    overall.finish()
    selected = _select_worker(
        runs,
        max_error_rate,
        min_throughput_ratio,
        max_retry_rate=max_retry_rate,
    )
    return BenchmarkResult(
        measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        runs=runs,
        selected_worker_count=selected.worker_count,
        max_error_rate=max_error_rate,
        min_throughput_ratio=min_throughput_ratio,
        max_retry_rate=max_retry_rate,
    )


def representative_sample(items: Sequence[T], max_count: int) -> list[T]:
    """전체 순서를 대표하도록 균등 간격 표본을 고른다."""
    if max_count <= 0:
        return []
    total = len(items)
    if total <= max_count:
        return list(items)
    if max_count == 1:
        return [items[0]]
    return [items[round(i * (total - 1) / (max_count - 1))] for i in range(max_count)]


def _measure_one(
    api_callable: Callable[[T, int], R],
    items: Sequence[T],
    worker_count: int,
    *,
    retry_count_from_result: Callable[[R], int] | None = None,
) -> WorkerRun:
    start = time.perf_counter()
    success_count = 0
    errors: list[str] = []
    retry_count = 0
    retry_item_count = 0
    retry_samples: list[str] = []
    progress = ProgressReporter(
        f"benchmark workers={worker_count}",
        len(items),
    )
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(api_callable, item, worker_count): item for item in items}
        for future in as_completed(futures):
            try:
                result = future.result()
                success_count += 1
                if retry_count_from_result is not None:
                    item_retry_count = retry_count_from_result(result)
                    retry_count += item_retry_count
                    if item_retry_count:
                        retry_item_count += 1
                        if len(retry_samples) < 5:
                            retry_samples.append(str(futures[future]))
                progress.advance()
            except Exception as exc:  # noqa: BLE001 - benchmark records boundary failures
                if len(errors) < 5:
                    errors.append(str(exc))
                progress.advance(errors=1)
    progress.finish()

    seconds = time.perf_counter() - start
    call_count = len(items)
    error_count = call_count - success_count
    return WorkerRun(
        worker_count=worker_count,
        call_count=call_count,
        success_count=success_count,
        error_count=error_count,
        seconds=seconds,
        errors=tuple(errors),
        retry_count=retry_count,
        retry_item_count=retry_item_count,
        retry_samples=tuple(retry_samples),
    )


def _select_worker(
    runs: Sequence[WorkerRun],
    max_error_rate: float,
    min_throughput_ratio: float,
    *,
    max_retry_rate: float | None = None,
) -> WorkerRun:
    acceptable = [
        run for run in runs if _is_run_acceptable(run, max_error_rate, max_retry_rate)
    ]
    if acceptable:
        best_throughput = max(run.calls_per_second for run in acceptable)
        near_best = [
            run
            for run in acceptable
            if run.calls_per_second >= best_throughput * min_throughput_ratio
        ]
        return min(near_best, key=lambda run: run.worker_count)
    return min(runs, key=lambda run: (run.error_rate, run.retry_rate, run.seconds, run.worker_count))


def _is_run_acceptable(
    run: WorkerRun,
    max_error_rate: float,
    max_retry_rate: float | None,
) -> bool:
    if run.error_rate >= max_error_rate:
        return False
    if max_retry_rate is not None and run.retry_rate > max_retry_rate:
        return False
    return True


def render_parallel_benchmark(result: BenchmarkResult, output_path: Path) -> None:
    """측정 결과를 Markdown 문서로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(result))


def _render_markdown(result: BenchmarkResult) -> str:
    retry_threshold = (
        ""
        if result.max_retry_rate is None
        else f", retry rate threshold: <= {result.max_retry_rate:.0%}"
    )
    lines = [
        "# Parallel Benchmark",
        "",
        f"Measured at: `{result.measured_at}`",
        "",
        "## Selected worker count",
        "",
        (
            f"`{result.selected_worker_count}` "
            f"(error rate threshold: < {result.max_error_rate:.0%}{retry_threshold})"
        ),
        "",
        "Selection policy: choose the lowest worker count that stays under the "
        f"error/retry thresholds and reaches at least {result.min_throughput_ratio:.0%} "
        "of the best measured throughput.",
        "",
        "## Results",
        "",
        "| Workers | Calls | Success | Errors | Error rate | Retried calls | Retry rate | Retries | Seconds | Calls/sec |",
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

    lines.extend(["", "## Calls/sec chart", "", "```text"])
    fastest = max((run.calls_per_second for run in result.runs), default=0)
    for run in result.runs:
        bar_len = 0 if fastest == 0 else max(1, round((run.calls_per_second / fastest) * 30))
        bar = "#" * bar_len
        lines.append(f"{run.worker_count:>3}: {bar} {run.calls_per_second:.2f}/s")
    lines.extend(["```", ""])

    error_lines = [
        f"- `{run.worker_count}` workers: {', '.join(run.errors)}"
        for run in result.runs
        if run.errors
    ]
    if error_lines:
        lines.extend(["## Sample Errors", "", *error_lines, ""])
    retry_lines = [
        f"- `{run.worker_count}` workers: {', '.join(run.retry_samples)}"
        for run in result.runs
        if run.retry_samples
    ]
    if retry_lines:
        lines.extend(["## Sample Retried Items", "", *retry_lines, ""])
    return "\n".join(lines)
