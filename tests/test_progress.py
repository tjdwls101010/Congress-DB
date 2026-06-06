from __future__ import annotations

import errno

from congress_db.core.progress import ProgressReporter, safe_print


class BrokenStream:
    def write(self, _text: str) -> None:
        raise OSError(errno.EIO, "Input/output error")

    def flush(self) -> None:
        raise OSError(errno.EIO, "Input/output error")


def test_safe_print_ignores_terminal_io_errors() -> None:
    safe_print("still running", file=BrokenStream(), flush=True)


def test_progress_reporter_ignores_terminal_io_errors() -> None:
    reporter = ProgressReporter("broken terminal", 2, stream=BrokenStream())

    reporter.start()
    reporter.advance()
    reporter.finish()
