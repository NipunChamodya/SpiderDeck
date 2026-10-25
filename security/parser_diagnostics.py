"""Discard document-derived parser diagnostics before they reach log handlers.

The application parses serially. A reentrant lock serializes our scoped changes
to third-party logger handlers and Python's process-wide warning hooks. This is
not a sandbox for arbitrary plugins or concurrent third-party configuration.
"""
from __future__ import annotations

import logging
import threading
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

_NAMESPACES = ('pdfminer', 'pdfplumber', 'openpyxl', 'docx', 'lxml', 'bs4', 'soupsieve')
_LOCK = threading.RLock()
OMITTED_DIAGNOSTICS = 'Parser diagnostics were omitted to protect document privacy.'


@dataclass
class ParserDiagnostics:
    count: int = 0


class _Discard(logging.Handler):
    def __init__(self, diagnostics: ParserDiagnostics):
        super().__init__()
        self.diagnostics = diagnostics

    def emit(self, record: logging.LogRecord) -> None:
        # Do not format, retain, hash or forward the potentially sensitive record.
        self.diagnostics.count += 1


@contextmanager
def private_parser_diagnostics() -> Iterator[ParserDiagnostics]:
    """Contain known parser logs/warnings, restoring hooks even after failure."""
    with _LOCK:
        diagnostics = ParserDiagnostics()
        discard = _Discard(diagnostics)
        # Parent loggers contain descendants created by lazy imports. Existing
        # descendants also need protection from their directly attached handlers.
        parents = [logging.getLogger(name) for name in _NAMESPACES]
        descendants = [logger for name, logger in list(logging.Logger.manager.loggerDict.items())
            if isinstance(logger, logging.Logger)
            and any(name.startswith(parent + '.') for parent in _NAMESPACES)]
        loggers = parents + descendants
        saved = [(logger, logger.handlers, logger.propagate) for logger in loggers]
        try:
            for logger in loggers:
                logger.handlers = [discard]
                logger.propagate = False
            with warnings.catch_warnings():
                warnings.simplefilter('always')
                def omit_warning(*args: object, **kwargs: object) -> None:
                    diagnostics.count += 1
                warnings.showwarning = omit_warning
                yield diagnostics
        finally:
            for logger, handlers, propagate in saved:
                logger.handlers = handlers
                logger.propagate = propagate
            discard.close()
