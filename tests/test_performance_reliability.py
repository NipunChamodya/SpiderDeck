"""Behavioral/resource-bound regressions; no machine-speed thresholds in CI."""
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmarks.run import pdf_fixture
from core.config import ImportConfig, RankingConfig
from core.models import ExtractedRecord, ImportResult
from core.storage import RecordStore
from handlers.local import DocumentImportError, import_document
from rank.models import ResearchIdea
from rank.supervisor_ranker import rank_records


def test_optimized_ranking_matches_preoptimization_snapshot():
    path = Path(__file__).parent / 'fixtures' / 'ranking_reference.json'
    fixture = json.loads(path.read_text())
    records = [ExtractedRecord(**{**row, 'extracted_at': datetime.fromisoformat(row['extracted_at'])})
               for row in fixture['records']]
    ideas = [ResearchIdea(**idea) for idea in fixture['ideas']]
    config = RankingConfig(**fixture['config'])
    actual = [result.to_dict() for result in rank_records(records, ideas, config)]
    assert json.loads(json.dumps(actual)) == fixture['expected']
    reversed_actual = [result.to_dict() for result in rank_records(list(reversed(records)), ideas, config)]
    assert json.loads(json.dumps(reversed_actual)) == fixture['expected']


def test_csv_bom_multiline_large_unicode_fields_and_duplicate_headers(tmp_path):
    import csv
    path = tmp_path / 'data.csv'
    payload = ('தமிழ் සිංහල research\n' * 800).strip()
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Name', 'Notes', 'Notes'])
        writer.writerow(['A', payload, 'last'])
    result = import_document(path)
    assert result.records[0].fields == {'Name': 'A', 'Notes': payload, 'Notes_2': 'last'}
    assert result.records[0].metadata['row'] == 2
    assert import_document(path).records[0].record_id == result.records[0].record_id


def test_input_validation_to_open_race_cannot_block_on_fifo(tmp_path):
    path = tmp_path / 'changed.txt'
    os.mkfifo(path, mode=0o600)
    # Simulate a previously validated regular file replaced before open(). The
    # child timeout makes this test fail safely if blocking FIFO opens regress.
    code = '''
import sys
from pathlib import Path
from unittest.mock import patch
from handlers.local import import_document,DocumentImportError
with patch('handlers.local.safe_input_path',return_value=Path(sys.argv[1])):
    try:
        import_document(sys.argv[1])
    except DocumentImportError:
        raise SystemExit(0)
raise SystemExit(1)
'''
    subprocess.run([sys.executable, '-B', '-c', code, str(path)], timeout=5, check=True)


def test_symlink_input_is_valid_but_postvalidation_symlink_replacement_is_not(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('original document')
    link = tmp_path / 'chosen.txt'
    link.symlink_to(source)
    assert import_document(link).records[0].source == str(source.resolve())
    with patch('handlers.local.safe_input_path', return_value=link):
        with pytest.raises(DocumentImportError):
            import_document(link)
    assert source.read_text() == 'original document'


def test_pdf_limit_stops_before_materializing_later_pages(tmp_path):
    from pdfplumber.page import Page
    path = tmp_path / 'many.pdf'
    path.write_bytes(pdf_fixture(100))
    original = Page.__init__
    constructed = []
    def track(page, *args, **kwargs):
        constructed.append(kwargs.get('page_number'))
        return original(page, *args, **kwargs)
    with patch.object(Page, '__init__', track):
        with pytest.raises(DocumentImportError, match='max_pdf_pages'):
            import_document(path, ImportConfig(max_pdf_pages=2))
    assert constructed == [1, 2]


def test_incremental_pdf_page_provenance_and_cleanup(tmp_path):
    from pdfplumber.page import Page
    path = tmp_path / 'three.pdf'
    path.write_bytes(pdf_fixture(3))
    original = Page.close
    closed = []
    def close(page):
        closed.append(page.page_number)
        return original(page)
    with patch.object(Page, 'close', close):
        result = import_document(path)
    assert [record.metadata['page'] for record in result.records] == [1, 2, 3]
    assert closed == [1, 2, 3]
    assert all('Synthetic research text' in record.text for record in result.records)


def test_pdf_permission_check_precedes_page_iteration(tmp_path):
    path = tmp_path / 'blocked.pdf'
    path.write_bytes(pdf_fixture(3))
    with patch('pdfplumber.open') as opened, patch('pdfminer.pdfpage.PDFPage.create_pages') as pages:
        opened.return_value.doc.is_extractable = False
        with pytest.raises(DocumentImportError, match='disallows text extraction'):
            import_document(path)
        pages.assert_not_called()


def test_reimport_collision_still_rolls_back_after_fast_duplicate_check(tmp_path):
    from core.storage import StorageError
    source = tmp_path / 'data.json'
    source.write_text('[{"nested":{"terms":["vision","தமிழ்"]}}]')
    store = RecordStore(tmp_path / 'output')
    result = import_document(source)
    store.save_import(result)
    changed = replace(result.records[0], fields={'nested': {'terms': ['changed']}})
    with pytest.raises(StorageError, match='collision'):
        store.save_import(replace(result, records=[changed]))
    assert store.search()[0].fields == result.records[0].fields


def test_persistence_keeps_public_serialization_and_timestamp_contract(tmp_path):
    source = tmp_path / 'data.json'
    source.write_text('[{"nested":{"values":[1,true,null,"தமிழ்"]}}]')
    imported = import_document(source)
    before = imported.records[0].to_dict()
    independent = imported.records[0].to_dict()
    independent['fields']['nested']['values'].append('not the original')
    assert imported.records[0].to_dict() == before
    store = RecordStore(tmp_path / 'output')
    assert store.save_import(imported).inserted == 1
    assert store.save_import(imported).duplicates == 1
    assert store.search()[0].to_dict() == before


def test_ranking_normalization_does_not_leak_across_comparisons(tmp_path):
    source = tmp_path / 'people.csv'
    source.write_text('Name,Expertise\nA,vision sensors\nB,wireless csi\n')
    records = import_document(source).records
    idea = ResearchIdea('vision', keywords=('vision',))
    assert rank_records(records, [idea])[0].matches[0].supervisor_name == 'A'
    changed = [replace(records[0], fields={'Name': 'A', 'Expertise': 'chemistry'}, text='chemistry'), records[1]]
    assert all(match.score == 0 for match in rank_records(changed, [idea])[0].matches)


@pytest.mark.parametrize('replacement', ['hello again', 'x', 'world'])
def test_input_modification_during_snapshot_is_rejected(tmp_path, replacement):
    path = tmp_path / 'document.txt'
    path.write_text('hello')
    original = os.fstat
    calls = 0
    def changed(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            before = original(fd)
            path.write_text(replacement)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000))
        return original(fd)
    with patch('handlers.local.os.fstat', side_effect=changed):
        with pytest.raises(DocumentImportError, match='changed while reading'):
            import_document(path)


def test_input_growth_beyond_file_limit_is_rejected(tmp_path):
    path = tmp_path / 'document.txt'
    path.write_text('hello')
    original = os.fstat
    calls = 0
    def changed(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text('hello again')
        return original(fd)
    with patch('handlers.local.os.fstat', side_effect=changed):
        with pytest.raises(DocumentImportError, match='grew beyond'):
            import_document(path, ImportConfig(max_file_bytes=5))
