"""Manually refreshed progress: no spinner, refresh thread, sleeps or fake totals."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterable, Iterator, TypeVar

from ui.display import motion_enabled, notice, terminal_text

T = TypeVar("T")


class Operation:
    def __init__(self, label: str, total: int | None = None, unit: str | None = None):
        self.label = terminal_text(label, 160)
        self.total = total
        self.completed = 0
        self.unit = terminal_text(unit, 40) if unit is not None else None
        self._progress = None
        self._task = None
        self._last_refresh = 0.0

    def start(self) -> None:
        if not motion_enabled():
            notice(self.label + "...")
            return
        from rich.console import Console
        from rich.progress import BarColumn, Progress, TextColumn
        columns = [TextColumn("{task.description}", markup=False)]
        if self.unit is not None:
            columns.append(TextColumn("{task.completed:.0f} {task.fields[unit]}", markup=False))
        if self.total is not None:
            columns = [columns[0], BarColumn(), TextColumn("{task.completed:.0f}/{task.total:.0f}")]
        self._progress = Progress(*columns, console=Console(markup=False), auto_refresh=False, transient=True)
        try:
            self._task = self._progress.add_task(self.label, total=self.total, unit=self.unit)
            self._progress.start()
            self._progress.refresh()
        except (OSError, UnicodeError):
            self.stop()

    def set_completed(self, completed: int) -> None:
        self.completed = completed
        if self._progress is None:
            return
        now = time.monotonic()
        refresh = now - self._last_refresh >= 0.1
        try:
            self._progress.update(self._task, completed=completed, refresh=refresh)
            if refresh:
                self._last_refresh = now
        except (OSError, UnicodeError):
            self.stop()

    def track(self, items: Iterable[T]) -> Iterator[T]:
        for item in items:
            yield item
            self.set_completed(self.completed + 1)

    def stop(self) -> None:
        progress, self._progress = self._progress, None
        if progress is not None:
            try:
                progress.stop()
            except (OSError, UnicodeError):
                pass  # A display failure must not roll back data or alter network policy.


@contextmanager
def operation(label: str, *, total: int | None = None, unit: str | None = None) -> Iterator[Operation]:
    state = Operation(label, total, unit)
    state.start()
    try:
        yield state
    finally:
        state.stop()
