"""Normalized, JSON-compatible local import records."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ExtractedRecord:
    record_id: str
    source: str
    source_type: str
    title: str
    text: str
    fields: dict[str, Any]
    extracted_at: datetime
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["extracted_at"] = self.extracted_at.isoformat().replace("+00:00", "Z")
        return result


@dataclass(frozen=True)
class ImportResult:
    source: str
    records: list[ExtractedRecord]
    warnings: list[str]
    size_bytes: int | None = None
