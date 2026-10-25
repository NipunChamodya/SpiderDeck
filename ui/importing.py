"""Native document selection, bounded safe preview, and persisted-source actions."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.config import ImportConfig
from core.storage import RecordStore, SearchFilters, StorageError
from handlers.local import DocumentImportError, import_document
from security.validators import UnsafePathError
from ui import menu, native, records
from ui.display import terminal_text
from ui.progress import operation


def choose_document() -> str | None:
    try:
        return native.select_document()
    except native.DialogUnavailable:
        print('Native file selection is unavailable in this session. Use a readable local path, or leave blank to cancel.')
        return menu.prompt_path('Local document to import:') or None


def run(config: ImportConfig, get_store: Callable[[], RecordStore], *, dry_run: bool = False) -> None:
    while True:
        try:
            requested = choose_document()
            if not requested:
                print('Import cancelled.')
                return
            if dry_run:
                print('Dry run: no document read.')
                return
            with operation('Extracting local document'):
                result = import_document(requested, config)
            with operation('Saving normalized records'):
                store = get_store()
                summary = store.save_import(result)
            print('Filename: ' + terminal_text(Path(result.source).name, 500))
            print(f'Document type: {Path(result.source).suffix.lstrip(".").upper()}; file size: {result.size_bytes} bytes.')
            print(f'Imported {len(result.records)} records; saved {summary.inserted} new records; '
                  f'skipped {summary.duplicates} duplicate identifiers.')
            print(f'Extracted characters: {sum(len(record.text) for record in result.records)}.')
            if result.records:
                print('Text preview (up to 300 characters): ' + terminal_text(result.records[0].text, 300))
            if summary.content_duplicates:
                print(f'{summary.content_duplicates} records have content already stored; source provenance retained.')
            if summary.reimported:
                print("This document's record set was imported previously.")
            for warning in result.warnings:
                print('Notice: ' + terminal_text(warning, 500))
            filters = SearchFilters(source=result.source, exact_source=True)
            del result
            print('Database: ' + terminal_text(str(store.path), 1000))
            while True:
                choice = menu.prompt_choice('Use this document (including earlier imports from the same file):',
                    ['Browse imported records', 'Search imported content', 'Import another document', 'Return to main menu'])
                if not choice or choice == 'Return to main menu':
                    return
                if choice == 'Import another document':
                    break
                records.browse(store, search=choice == 'Search imported content', filters=filters)
        except menu.PromptCancelled:
            print('Import cancelled. Previously committed records remain saved.')
            return
        except DocumentImportError as exc:
            print('Import failed: ' + str(exc))
            return
        except (StorageError, OSError, UnsafePathError):
            print('Storage failed. Check output permissions, free space and database locks; existing records were preserved.')
            return
