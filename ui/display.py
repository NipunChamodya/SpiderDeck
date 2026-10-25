"""Scoped display preferences; presentation never changes authorization policy."""
from __future__ import annotations

import os
import sys
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class DisplayOptions:
    quiet: bool = False
    plain: bool = False
    reduced_motion: bool = False
    animate: bool = False


_OPTIONS = ContextVar("spiderdeck_display", default=DisplayOptions())


def options() -> DisplayOptions:
    return _OPTIONS.get()


@contextmanager
def use_options(value: DisplayOptions) -> Iterator[None]:
    token = _OPTIONS.set(value)
    try:
        yield
    finally:
        _OPTIONS.reset(token)


def terminal_text(value: str, max_chars: int = 160) -> str:
    return "".join(char if char in {"\u200c","\u200d"} or not unicodedata.category(char).startswith("C") else " "
                   for char in str(value)[:max_chars])


def interactive_terminal() -> bool:
    return (not options().plain and os.environ.get("TERM", "") != "dumb"
            and sys.stdin.isatty() and sys.stdout.isatty())


def motion_enabled() -> bool:
    return (interactive_terminal() and not options().plain
            and not options().reduced_motion and not options().quiet)


def notice(message: str) -> None:
    if not options().quiet:
        print(terminal_text(message, 1000))


def banner() -> None:
    notice("SPIDERDECK  |  LOCAL RESEARCH INTELLIGENCE")
    notice("Local documents, SQLite search, explainable ranking, authorized collection.")
