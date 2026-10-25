"""Legacy logging interface, with no implicit file writes or source logging.

Active crawler auditing uses exclusive private files under the configured output
root. This compatibility helper intentionally has no default external sink.
"""
from __future__ import annotations

import logging

_STATUSES = frozenset({'success', 'failed', 'blocked', 'cancelled', 'completed'})


def get_logger(name: str = 'spiderdeck') -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def log_access(logger: logging.Logger, source: str, status: str, items: int = 0) -> None:
    """Log fixed status/count fields; discard the legacy raw source argument."""
    safe_status = status if type(status) is str and status in _STATUSES else 'unknown'
    count = items if type(items) is int and 0 <= items <= 1_000_000 else 0
    logger.info('ACCESS status=%s items_collected=%d', safe_status, count)
