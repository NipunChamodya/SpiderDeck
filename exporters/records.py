"""Deterministic, UTF-8 exports without overwriting existing files."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from core.models import ExtractedRecord
from core.storage import canonical_json
from security.filesystem import new_output_text, output_directory

CSV_COLUMNS = ("record_id", "source", "source_type", "title", "text", "fields",
               "extracted_at", "metadata")


def spreadsheet_safe(value: str) -> str:
    """Prefix dangerous cells, including formulas concealed behind whitespace."""
    stripped = value.lstrip()
    if value.startswith(("\t", "\r", "\n")) or stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_records(records: Iterable[ExtractedRecord], output_dir: str | Path,
                   filename: str, format: str) -> int:
    if format not in {"csv", "json"}:
        raise ValueError("Export format must be csv or json.")
    if Path(filename).suffix.lower() != "." + format:
        raise ValueError("Export filename must have the selected format's extension.")
    root = output_directory(output_dir)
    count = 0
    with new_output_text(root, filename) as handle:
        if format == "csv":
            writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
            writer.writerow(CSV_COLUMNS)
            for record in records:
                payload = record.to_dict()
                payload["fields"] = canonical_json(payload["fields"])
                payload["metadata"] = canonical_json(payload["metadata"])
                writer.writerow([spreadsheet_safe(str(payload[column])) for column in CSV_COLUMNS])
                count += 1
        else:
            handle.write("[\n")
            for record in records:
                if count:
                    handle.write(",\n")
                json.dump(record.to_dict(), handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
                count += 1
            handle.write("\n]\n")
    return count
