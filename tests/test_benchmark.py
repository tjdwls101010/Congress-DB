"""Slice 4 — 병렬 워커 측정 검증."""

from __future__ import annotations

from pathlib import Path

from congress_db.benchmark import (
    WorkerRun,
    _select_worker,
    measure_workers,
    render_parallel_benchmark,
)


def test_measure_workers_selects_fastest_successful_level() -> None:
    calls: list[tuple[int, str]] = []

    def api_callable(item: str, worker_count: int) -> str:
        calls.append((worker_count, item))
        if worker_count == 20:
            raise RuntimeError("rate limited")
        return item

    result = measure_workers(
        api_callable,
        items=["A", "B", "C"],
        levels=(5, 20),
        max_error_rate=0.01,
    )

    assert result.selected_worker_count == 5
    assert result.runs[0].worker_count == 5
    assert result.runs[0].error_rate == 0
    assert result.runs[1].worker_count == 20
    assert result.runs[1].error_rate == 1
    assert calls == [
        (5, "A"),
        (5, "B"),
        (5, "C"),
        (20, "A"),
        (20, "B"),
        (20, "C"),
    ]


def test_measure_workers_prefers_lower_worker_when_throughput_is_close() -> None:
    selected = _select_worker(
        (
            WorkerRun(5, call_count=100, success_count=100, error_count=0, seconds=7.0),
            WorkerRun(20, call_count=100, success_count=100, error_count=0, seconds=4.18),
            WorkerRun(50, call_count=100, success_count=100, error_count=0, seconds=4.0),
            WorkerRun(100, call_count=100, success_count=100, error_count=0, seconds=3.98),
        ),
        max_error_rate=0.01,
        min_throughput_ratio=0.95,
    )

    assert selected.worker_count == 20


def test_render_parallel_benchmark_writes_table_and_chart(tmp_path: Path) -> None:
    result = measure_workers(
        lambda item, worker_count: item,
        items=["A", "B"],
        levels=(5,),
    )
    output = tmp_path / "PARALLEL-BENCHMARK.md"

    render_parallel_benchmark(result, output)

    md = output.read_text()
    assert "| Workers | Calls | Success | Errors | Error rate | Seconds | Calls/sec |" in md
    assert "## Selected worker count" in md
    assert "Selection policy" in md
    assert "`5`" in md
    assert "```text" in md
