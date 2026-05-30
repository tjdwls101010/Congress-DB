"""터미널 진행률 출력."""

from __future__ import annotations

import sys
import time
from typing import Any, TextIO


def safe_print(*args: Any, **kwargs: Any) -> None:
    """터미널 출력 실패가 수집 실행 실패로 번지지 않게 한다."""
    try:
        print(*args, **kwargs)
    except (BrokenPipeError, OSError):
        return


class ProgressReporter:
    """긴 적재 작업의 진행 상황을 주기적으로 출력한다."""

    def __init__(
        self,
        label: str,
        total: int,
        *,
        min_interval: float = 2.0,
        step: int | None = None,
        stream: TextIO = sys.stderr,
        enabled: bool = True,
    ) -> None:
        self.label = label
        self.total = max(total, 0)
        self.min_interval = min_interval
        self.step = step or max(1, self.total // 20)
        self.stream = stream
        self.enabled = enabled
        self.done_count = 0
        self.error_count = 0
        self.started_at = time.perf_counter()
        self.last_printed_at = 0.0
        self.last_printed_done = -1

    def start(self) -> None:
        self._print("start")

    def advance(self, *, errors: int = 0, count: int = 1) -> None:
        self.done_count += count
        self.error_count += errors
        self._maybe_print()

    def set(self, done: int, *, errors: int | None = None) -> None:
        self.done_count = done
        if errors is not None:
            self.error_count = errors
        self._maybe_print()

    def finish(self) -> None:
        self._print("done", force=True)

    def _maybe_print(self) -> None:
        now = time.perf_counter()
        reached_step = self.done_count == self.total or (
            self.done_count // self.step != self.last_printed_done // self.step
        )
        reached_time = now - self.last_printed_at >= self.min_interval
        if reached_step or reached_time:
            self._print("progress")

    def _print(self, state: str, *, force: bool = False) -> None:
        if not self.enabled:
            return
        if not force and state == "progress" and self.done_count == self.last_printed_done:
            return
        elapsed = max(time.perf_counter() - self.started_at, 0.001)
        rate = self.done_count / elapsed
        safe_print(
            f"[progress] {self.label}: {state} "
            f"{self.done_count}/{self.total} errors={self.error_count} "
            f"elapsed={elapsed:.1f}s rate={rate:.2f}/s",
            file=self.stream,
            flush=True,
        )
        self.last_printed_at = time.perf_counter()
        self.last_printed_done = self.done_count
