"""Opt-in library progress, enabled by CLI work phases (plain stderr, never stdout)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, Thread
from time import monotonic


class _Progress:
    def __init__(self, interval: float):
        self.interval = interval
        self.stream = sys.stderr
        self.stopped = Event()
        self.lock = Lock()
        self.message = ""
        self.since = monotonic()

    def update(self, message: str) -> None:
        with self.lock:
            self.message = message
            self.since = monotonic()
            print(f"[reducto] {message}", file=self.stream, flush=True)

    def heartbeat(self) -> None:
        while not self.stopped.wait(self.interval):
            with self.lock:
                elapsed = monotonic() - self.since
                if elapsed >= self.interval:
                    print(
                        f"[reducto] Still working: {self.message} ({elapsed:.0f}s elapsed)",
                        file=self.stream,
                        flush=True,
                    )


_active: ContextVar[_Progress | None] = ContextVar("reducto_progress", default=None)


def status(message: str) -> None:
    """Report a stage only when a CLI progress context is active."""
    reporter = _active.get()
    if reporter is not None:
        reporter.update(message)


@contextmanager
def progress(message: str, *, quiet: bool = False, interval: float = 5.0) -> Iterator[None]:
    """Show a stage immediately and keep long phases visibly alive until they end."""
    if interval <= 0:
        raise ValueError("Progress interval must be positive")
    reporter = None if quiet else _Progress(interval)
    token = _active.set(reporter)
    thread = None
    try:
        if reporter is not None:
            reporter.update(message)
            thread = Thread(target=reporter.heartbeat, name="reducto-progress", daemon=True)
            thread.start()
        yield
    finally:
        if reporter is not None:
            reporter.stopped.set()
        if thread is not None:
            thread.join()
        _active.reset(token)
