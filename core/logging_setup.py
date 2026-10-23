from __future__ import annotations

import logging
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def get_logger(name: str = "spiderdeck") -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_DIR / "spiderdeck.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(file_handler)

    return logger


def log_access(logger: logging.Logger, source: str, status: str, items: int = 0) -> None:
    """
    Structured audit-trail entry. Logs WHAT was accessed and WHEN, never the
    page/file content itself (content may include personal data in transit).
    """
    logger.info("ACCESS source=%s status=%s items_collected=%d", source, status, items)
