"""Small record workflows using the existing questionary menu navigation."""
from __future__ import annotations
from dataclasses import replace

from core.storage import RecordStore, SearchFilters
from exporters.records import export_records
from ui import menu
from ui.display import terminal_text
from ui.progress import operation


def prompt_filters() -> SearchFilters:
    return SearchFilters(menu.prompt_text("Keyword (blank for all):"),
                         menu.prompt_text("Source path contains (blank for all):"),
                         menu.prompt_text("Document type, e.g. csv (blank for all):"))


def browse(store: RecordStore, *, search: bool = False, filters: SearchFilters | None = None) -> None:
    if filters is None:
        filters = prompt_filters() if search else SearchFilters()
    elif search:
        filters = replace(filters, keyword=menu.prompt_text('Keyword in this source (blank for all):'))
    with operation("Searching local records"):
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


def export(store: RecordStore, *, dry_run: bool = False, filters: SearchFilters | None = None) -> None:
    filters = prompt_filters() if filters is None else filters
    filename = menu.prompt_text("New export filename under output (e.g. results.csv or results.json):")
    if not filename:
        return
    format = filename.rsplit(".", 1)[-1].lower()
    if dry_run:
        print("Dry run: no export written.")
        return
    records = store.iter_records(filters)
    try:
        with operation("Exporting records", total=store.count(filters)) as progress:
            count = export_records(progress.track(records), store.root, filename, format)
    finally:
        records.close()
    print(f"Exported {count} records to {terminal_text(filename)}.")
