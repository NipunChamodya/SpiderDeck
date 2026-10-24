"""Small record workflows using the existing questionary menu navigation."""
from __future__ import annotations

import unicodedata

from core.storage import RecordStore, SearchFilters
from exporters.records import export_records
from ui import menu


def terminal_text(value: str, max_chars: int = 160) -> str:
    # Imported text must not inject terminal escape/control sequences.
    return "".join(char if not unicodedata.category(char).startswith("C")
                   else " " for char in value[:max_chars])


def prompt_filters() -> SearchFilters:
    return SearchFilters(menu.prompt_text("Keyword (blank for all):"),
                         menu.prompt_text("Source path contains (blank for all):"),
                         menu.prompt_text("Document type, e.g. csv (blank for all):"))


def browse(store: RecordStore, *, search: bool = False) -> None:
    filters = prompt_filters() if search else SearchFilters()
    total = store.count(filters)
    print(f"{total} matching records.")
    offset = 0
    while offset < total:
        records = store.search(filters, limit=20, offset=offset)
        if not records:
            break
        for record in records:
            print(f"{record.record_id[:12]} | {terminal_text(record.title)} | "
                  f"{terminal_text(record.source_type)} | {terminal_text(record.source)}")
            print(f"  {terminal_text(record.text, 240)}")
        offset += len(records)
        if offset >= total or not menu.confirm("Show next page?"):
            break


def export(store: RecordStore, *, dry_run: bool = False) -> None:
    filters = prompt_filters()
    filename = menu.prompt_text("New export filename under output (e.g. results.csv or results.json):")
    if not filename:
        return
    format = filename.rsplit(".", 1)[-1].lower()
    if dry_run:
        print("Dry run: no export written.")
        return
    records = store.iter_records(filters)
    try:
        count = export_records(records, store.root, filename, format)
    finally:
        records.close()
    print(f"Exported {count} records to {terminal_text(filename)}.")
