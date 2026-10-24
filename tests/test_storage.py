"""Offline unit and end-to-end persistence/export tests."""
import csv
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core.models import ImportResult
from core.storage import APPLICATION_ID, DATABASE_NAME, SCHEMA_VERSION, RecordStore, SearchFilters, StorageError
from exporters.records import export_records, spreadsheet_safe
from handlers.local import import_document
from security.validators import UnsafePathError


@pytest.fixture
def document(tmp_path):
    path = tmp_path / 'people.csv'
    path.write_text('Name,Expertise\nනිපුන්,Vision and sensors\nதமிழ்,Wireless CSI\n', encoding='utf-8')
    return path


@pytest.fixture
def store(tmp_path):
    return RecordStore(tmp_path / 'output')


def test_persistence_round_trip_and_schema(store, document):
    result = import_document(document)
    assert store.save_import(result).inserted == 2
    reopened = RecordStore(store.root)
    assert reopened.count() == 2
    actual = {r.record_id: r.to_dict() for r in reopened.search()}
    assert actual == {r.record_id: r.to_dict() for r in result.records}
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert connection.execute('PRAGMA application_id').fetchone()[0] == APPLICATION_ID
    assert store.path.stat().st_mode & 0o077 == 0


def test_reimports_skip_ids_and_preserve_original_timestamp(store, document):
    result = import_document(document)
    store.save_import(result)
    summary = store.save_import(import_document(document))
    assert (summary.inserted, summary.duplicates, summary.reimported) == (0, 2, True)
    original = {r.record_id: r.to_dict() for r in result.records}
    assert {r.record_id: r.to_dict() for r in store.search()} == original


def test_cross_source_duplicates_keep_provenance_and_changed_import_is_additive(store, document, tmp_path):
    store.save_import(import_document(document))
    copied = tmp_path / 'copy.csv'
    copied.write_bytes(document.read_bytes())
    summary = store.save_import(import_document(copied))
    assert summary.content_duplicates == 2
    assert summary.inserted == 2
    assert store.count() == 4
    document.write_text('Name,Expertise\nA,New research\n', encoding='utf-8')
    assert store.save_import(import_document(document)).inserted == 1
    assert store.count() == 5  # Old records are never silently removed.


def test_transaction_rolls_back_records_and_import_manifest(store, document):
    result = import_document(document)
    bad = replace(result.records[1], source='wrong source')
    with pytest.raises(StorageError, match='provenance'):
        store.save_import(replace(result, records=[result.records[0], bad]))
    assert store.count() == 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('SELECT count(*) FROM imports').fetchone()[0] == 0
    assert store.save_import(result).inserted == 2


def test_id_collision_does_not_overwrite_or_commit_partial_import(store, document):
    result = import_document(document)
    store.save_import(result)
    fresh = replace(result.records[0], record_id='new-id', text='New record')
    collision = replace(result.records[1], text='Different text with existing ID')
    with pytest.raises(StorageError, match='collision'):
        store.save_import(replace(result, records=[fresh, collision]))
    assert store.count() == 2
    assert not store.search(SearchFilters(keyword='New record'))


def test_search_filters_are_literal_unicode_and_parameterized(store, document):
    store.save_import(import_document(document))
    assert len(store.search(SearchFilters(keyword='VISION'))) == 1
    assert len(store.search(SearchFilters(keyword='தமிழ்'))) == 1
    assert len(store.search(SearchFilters(keyword='නිපුන්'))) == 1
    assert store.count(SearchFilters(source=document.name, source_type='.CSV')) == 2
    assert store.count(SearchFilters(keyword='vision', source='people', source_type='csv')) == 1
    for value in ["' OR 1=1 --", '%', '_', '"; DROP TABLE records; --']:
        assert store.count(SearchFilters(keyword=value)) == 0
        expected = 2 if value in str(document) else 0
        assert store.count(SearchFilters(source=value)) == expected
        assert store.count(SearchFilters(source_type=value)) == 0
    assert store.count() == 2
    ordered = store.search()
    assert store.search(limit=1) + store.search(limit=1, offset=1) == ordered


def test_search_casefold_and_normalization(store, document):
    result = import_document(document)
    record = replace(result.records[0], text='Straße café', record_id='unicode')
    store.save_import(replace(result, records=[record]))
    assert store.count(SearchFilters(keyword='STRASSE')) == 1
    assert store.count(SearchFilters(keyword='cafe\u0301')) == 1


@pytest.mark.parametrize('version', [0, 2, 999])
def test_unsupported_versions_never_migrated(store, version):
    with sqlite3.connect(store.path) as connection:
        connection.execute(f'PRAGMA user_version={version}')
    before = store.path.read_bytes()
    with pytest.raises(StorageError, match='schema version'):
        RecordStore(store.root)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('existing', [b'', b'important user file'])
def test_existing_unrelated_files_preserved(tmp_path, existing):
    root = tmp_path / 'output'
    root.mkdir()
    path = root / DATABASE_NAME
    path.write_bytes(existing)
    path.chmod(0o600)
    with pytest.raises(StorageError):
        RecordStore(root)
    assert path.read_bytes() == existing


def test_unrelated_sqlite_database_preserved(tmp_path):
    root = tmp_path / 'output'
    root.mkdir()
    path = root / DATABASE_NAME
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE personal_data (value TEXT)')
        connection.execute("INSERT INTO personal_data VALUES ('keep me')")
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(StorageError):
        RecordStore(root)
    assert path.read_bytes() == before


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'sidecar', 'permissions'])
def test_unsafe_database_paths_refused(tmp_path, kind):
    root = tmp_path / 'output'
    root.mkdir()
    outside = tmp_path / 'private'
    outside.write_bytes(b'outside data')
    outside.chmod(0o600)
    if kind == 'symlink':
        (root / DATABASE_NAME).symlink_to(outside)
    elif kind == 'hardlink':
        os.link(outside, root / DATABASE_NAME)
    elif kind == 'sidecar':
        store = RecordStore(root)
        (root / (DATABASE_NAME + '-journal')).symlink_to(outside)
    else:
        store = RecordStore(root)
        store.path.chmod(0o644)
    with pytest.raises(StorageError):
        RecordStore(root)
    assert outside.read_bytes() == b'outside data'


def test_missing_database_not_recreated(store):
    store.path.unlink()
    with pytest.raises(StorageError, match='disappeared'):
        store.count()
    assert not store.path.exists()


def test_unsafe_directory_refused(tmp_path):
    root = tmp_path / 'output'
    root.mkdir()
    root.chmod(0o777)
    with pytest.raises(StorageError):
        RecordStore(root)
    assert not (root / DATABASE_NAME).exists()
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(StorageError):
        RecordStore(link)


def test_exports_round_trip_and_determinism(store, document):
    store.save_import(import_document(document))
    assert export_records(store.iter_records(), store.root, 'one.json', 'json') == 2
    assert export_records(store.iter_records(), store.root, 'two.json', 'json') == 2
    assert (store.root / 'one.json').read_bytes() == (store.root / 'two.json').read_bytes()
    payload = json.loads((store.root / 'one.json').read_text())
    assert payload == [r.to_dict() for r in store.search()]
    assert export_records(store.iter_records(), store.root, 'data.csv', 'csv') == 2
    with (store.root / 'data.csv').open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert json.loads(rows[0]['fields']) == store.search()[0].fields
    assert 'නිපුන්'.encode() in (store.root / 'data.csv').read_bytes()
    assert (store.root / 'one.json').stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('cell', ['=SUM(1,2)', '+1+2', '-3', '@SUM(A1)', '  =1', '\t=1', '\n+1', '\rtext'])
def test_formula_injection(cell, store, document):
    result = import_document(document)
    record = replace(result.records[0], title=cell, text=cell, source=cell)
    export_records([record], store.root, 'formulas.csv', 'csv')
    with (store.root / 'formulas.csv').open(newline='', encoding='utf-8') as handle:
        row = next(csv.DictReader(handle))
    for key in ['title', 'text', 'source']:
        assert row[key] == "'" + cell
    assert spreadsheet_safe('தமிழ்') == 'தமிழ்'


@pytest.mark.parametrize('filename', ['../escape.json', '/tmp/escape.json', 'nested/data.json', '..\\escape.json', '.hidden.json'])
def test_export_path_rejections(store, filename):
    with pytest.raises((UnsafePathError, ValueError)):
        export_records([], store.root, filename, 'json')


def test_existing_export_and_symlink_preserved(store, tmp_path):
    export_records([], store.root, 'keep.json', 'json')
    before = (store.root / 'keep.json').read_bytes()
    with pytest.raises(FileExistsError):
        export_records([], store.root, 'keep.json', 'json')
    assert (store.root / 'keep.json').read_bytes() == before
    outside = tmp_path / 'outside.json'
    outside.write_text('KEEP')
    (store.root / 'link.json').symlink_to(outside)
    with pytest.raises((UnsafePathError, FileExistsError)):
        export_records([], store.root, 'link.json', 'json')
    assert outside.read_text() == 'KEEP'
    assert not list(store.root.glob('.export-*.tmp'))


def test_failed_stream_not_published(store, document):
    record = import_document(document).records[0]
    def failing_stream():
        yield record
        raise ValueError('failure while streaming')
    with pytest.raises(ValueError):
        export_records(failing_stream(), store.root, 'partial.json', 'json')
    assert not (store.root / 'partial.json').exists()
    assert not list(store.root.glob('.export-*.tmp'))


def test_offline_import_search_export_integration(store, document):
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        result = import_document(document)
        assert store.save_import(result).inserted == 2
        assert store.save_import(import_document(document)).duplicates == 2
        reopened = RecordStore(store.root)
        selected = reopened.iter_records(SearchFilters(keyword='vision', source_type='csv'))
        assert export_records(selected, reopened.root, 'selection.json', 'json') == 1
    payload = json.loads((store.root / 'selection.json').read_text())
    assert payload[0]['fields']['Name'] == 'නිපුන්'


def test_terminal_control_sequences_removed():
    from ui.records import terminal_text
    assert '\x1b' not in terminal_text('\x1b[31mHostile\x07\n')
    assert '\x07' not in terminal_text('\x07')


def test_directory_replaced_during_export_refused(store, document, tmp_path):
    record = import_document(document).records[0]
    original = store.root
    moved = tmp_path / 'moved-output'
    outside = tmp_path / 'outside'
    outside.mkdir()
    def swapping_stream():
        yield record
        original.rename(moved)
        original.symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError, match='changed'):
        export_records(swapping_stream(), original, 'escape.json', 'json')
    assert not (outside / 'escape.json').exists()
    assert not (moved / 'escape.json').exists()
    assert not list(moved.glob('.export-*.tmp'))


def test_database_error_rolls_back_import(store, document):
    result = import_document(document)
    # A late iterator failure exercises transaction rollback after a real INSERT.
    class FailingRecords(list):
        calls = 0
        def __iter__(self):
            self.calls += 1
            if self.calls == 1:  # manifest computation
                yield from super().__iter__()
                return
            yield self[0]
            raise sqlite3.OperationalError('simulated disk failure')
    with pytest.raises(StorageError):
        store.save_import(replace(result, records=FailingRecords(result.records)))
    assert store.count() == 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('SELECT count(*) FROM imports').fetchone()[0] == 0


def test_database_lock_is_actionable_and_preserves_data(store, document):
    # timeout=5 is intentionally bounded; use a short connect timeout for this fixture.
    store.save_import(import_document(document))
    original_connect = sqlite3.connect
    def fast_connect(*args, **kwargs):
        kwargs['timeout'] = 0.01
        return original_connect(*args, **kwargs)
    with original_connect(store.path) as blocker:
        blocker.execute('BEGIN EXCLUSIVE')
        with patch('core.storage.sqlite3.connect', side_effect=fast_connect):
            with pytest.raises(StorageError, match='locks'):
                store.save_import(import_document(document))
        blocker.rollback()
    assert store.count() == 2


def test_menu_persistence_browse_search_export(tmp_path, document, monkeypatch, capsys):
    import argparse
    import spiderdeck
    from core.config import AppConfig, CrawlConfig, OutputConfig
    from ui import menu
    from fx import effects
    root = tmp_path / 'output'
    monkeypatch.setattr('core.config.load_config', lambda: AppConfig(CrawlConfig(), OutputConfig(str(root))))
    monkeypatch.setattr(spiderdeck, 'run_security_check', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **_: None)
    monkeypatch.setattr(effects, 'glitch_title', lambda *_, **__: None)
    monkeypatch.setattr(menu, 'prompt_path', lambda _: str(document))
    choices = iter(['2) Import', '8) Quit'])
    monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
    spiderdeck.run_menu(argparse.Namespace(no_fx=True, dry_run=False))
    assert RecordStore(root).count() == 2
    choices = iter(['2) Import', '3) Browse', '4) Search', '9) Export', '8) Quit'])
    answers = iter(['vision', '', 'csv', 'vision', '', 'csv', 'selected.json'])
    monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
    monkeypatch.setattr(menu, 'prompt_text', lambda _: next(answers))
    spiderdeck.run_menu(argparse.Namespace(no_fx=True, dry_run=False))
    output = capsys.readouterr().out
    assert 'skipped 2 duplicate identifiers' in output
    assert '1 matching records' in output
    assert 'Exported 1 records' in output
    assert len(json.loads((root / 'selected.json').read_text())) == 1
    assert RecordStore(root).count() == 2


def test_menu_dry_run_never_creates_database(tmp_path, monkeypatch):
    import argparse
    import spiderdeck
    from core.config import AppConfig, CrawlConfig, OutputConfig
    from ui import menu
    from fx import effects
    root = tmp_path / 'output'
    monkeypatch.setattr('core.config.load_config', lambda: AppConfig(CrawlConfig(), OutputConfig(str(root))))
    monkeypatch.setattr(spiderdeck, 'run_security_check', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **_: None)
    monkeypatch.setattr(effects, 'glitch_title', lambda *_, **__: None)
    choices = iter(['2) Import', '3) Browse', '4) Search', '9) Export', '8) Quit'])
    monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
    monkeypatch.setattr(menu, 'prompt_path', lambda _: 'not-read.txt')
    spiderdeck.run_menu(argparse.Namespace(no_fx=True, dry_run=True))
    assert not root.exists()


def test_paged_browse_caps_materialized_records(store, tmp_path, monkeypatch, capsys):
    from ui import menu
    from ui.records import browse
    path = tmp_path / 'many.csv'
    path.write_text('n\n' + '\n'.join(str(i) for i in range(45)))
    store.save_import(import_document(path))
    answers = iter([True, False])
    monkeypatch.setattr(menu, 'confirm', lambda _: next(answers))
    with patch.object(store, 'search', wraps=store.search) as search:
        browse(store)
    assert [call.kwargs for call in search.call_args_list] == [
        {'limit': 20, 'offset': 0}, {'limit': 20, 'offset': 20}]
    assert '45 matching records' in capsys.readouterr().out


@pytest.mark.parametrize('suffix,text', [('txt', 'notes'), ('md', '# Notes'),
    ('json', '[{"name":"தமிழ்","nested":{"x":[1,true,null]}}]'),
    ('html', '<title>Notes</title><p>නිපුන්</p>')])
def test_other_text_formats_persist_and_export(store, tmp_path, suffix, text):
    path = tmp_path / f'notes.{suffix}'
    path.write_text(text, encoding='utf-8')
    result = import_document(path)
    store.save_import(result)
    export_records(store.iter_records(), store.root, 'out.json', 'json')
    assert json.loads((store.root / 'out.json').read_text()) == [r.to_dict() for r in result.records]


def test_special_database_sidecar_refused_without_blocking(store):
    os.mkfifo(store.root / (DATABASE_NAME + '-journal'), mode=0o600)
    with pytest.raises(StorageError):
        store.count()


def test_tampered_schema_refused(store):
    with sqlite3.connect(store.path) as connection:
        connection.execute('CREATE VIEW untrusted AS SELECT * FROM records')
    with pytest.raises(StorageError, match='schema objects'):
        store.count()
