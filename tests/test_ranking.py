"""Toy ranking fixtures: ordering assertions are not real-world evaluation data."""
import json
import math
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.config import RankingConfig, load_config
from core.models import ExtractedRecord
from core.storage import RecordStore, StorageError
from rank.models import ResearchIdea, SCORE_NOTICE
from rank.supervisor_ranker import RankingError, rank_records, tokenize


def record(name, expertise, source='fixture.csv', identifier=None, **extra):
    fields = {'Name': name, 'Expertise': expertise, **extra}
    return ExtractedRecord(identifier or (source + name + expertise), source, 'csv', source,
        '\n'.join(f'{key}: {value}' for key, value in fields.items()), fields,
        datetime(2026, 1, 1, tzinfo=timezone.utc), {'row': 2})


@pytest.fixture
def records():
    return [record('Vision researcher', 'fish freshness computer vision sensors'),
            record('Wireless researcher', 'wi-fi csi fall detection interference'),
            record('Security researcher', 'client-side phishing detection webassembly'),
            record('Forensics researcher', 'digital evidence tracing image distribution')]


@pytest.fixture
def store(tmp_path):
    return RecordStore(tmp_path / 'output')


def test_expected_toy_ordering_multiple_ideas(records):
    ideas = [ResearchIdea('Fish freshness', 'computer vision sensors'),
             ResearchIdea('Wi-Fi fall detection', 'csi interference'),
             ResearchIdea('Phishing detection', 'client-side webassembly'),
             ResearchIdea('Digital evidence', 'tracing image distribution')]
    results = rank_records(records, ideas)
    assert [result.matches[0].supervisor_name for result in results] == [
        'Vision researcher', 'Wireless researcher', 'Security researcher', 'Forensics researcher']
    for result in results:
        assert result.matches[0].score > result.matches[-1].score
        assert result.matches[0].matched_terms
        assert result.matches[0].sources == ('fixture.csv',)
        assert result.matches[0].record_ids
        assert 'TF-IDF cosine=' in result.matches[0].reason
        assert result.score_notice == SCORE_NOTICE
        json.dumps(result.to_dict(), allow_nan=False)


def test_blank_description_and_missing_expertise():
    row = replace(record('A', 'computer vision'), fields={'Name': 'A'}, text='computer vision')
    result = rank_records([row], [ResearchIdea('computer vision')])[0]
    assert result.matches[0].score > 0
    assert any('Description is empty' in warning for warning in result.warnings)
    assert any('full record text' in warning for warning in result.matches[0].uncertainties)


def test_missing_supervisor_name():
    row = replace(record('A', 'vision'), fields={}, text='vision')
    result = rank_records([row], [ResearchIdea('vision')])[0]
    assert result.matches[0].supervisor_name is None
    assert any('name is missing' in value for value in result.matches[0].uncertainties)


def test_no_records_and_no_ideas():
    result = rank_records([], [ResearchIdea('vision')])[0]
    assert not result.matches
    assert result.candidate_count == 0
    assert result.warnings
    with pytest.raises(RankingError, match='at least one'):
        rank_records([], [])


@pytest.mark.parametrize('expertise', ['', '!!!', 'quantum chemistry'])
def test_zero_similarity_is_explicit(expertise):
    row = replace(record('A', expertise), text=expertise, fields={})
    result = rank_records([row], [ResearchIdea('computer vision')])[0]
    assert result.matches[0].score == 0
    assert result.matches[0].matched_terms == ()
    assert 'No relevance' in result.matches[0].reason
    assert any('similarity is zero' in warning for warning in result.warnings)


@pytest.mark.parametrize('text', ['සිංහල පර්යේෂණ', 'தமிழ் ஆராய்ச்சி', 'English research'])
def test_unicode_tokens_and_matching(text):
    assert tokenize(text) == text.lower().split()
    good = record('Relevant', text)
    other = record('Other', 'unrelated physics')
    result = rank_records([other, good], [ResearchIdea(text)])[0]
    assert result.matches[0].supervisor_name == 'Relevant'
    assert result.matches[0].score > 0


def test_exact_copies_do_not_boost_scores_or_discard_provenance(records):
    idea = ResearchIdea('computer vision sensors')
    original = rank_records(records, [idea])[0]
    copied = replace(records[0], source='copy.csv', record_id='copy-id')
    with_copy = rank_records(records + [copied], [idea])[0]
    assert with_copy.candidate_count == original.candidate_count
    assert [m.score for m in with_copy.matches] == [m.score for m in original.matches]
    best = with_copy.matches[0]
    assert best.sources == ('copy.csv', 'fixture.csv')
    assert len(best.record_ids) == 2


def test_same_names_at_different_affiliations_stay_separate():
    rows = [record('Alex', 'vision', 'a.csv', Affiliation='University A'),
            record('Alex', 'wireless', 'b.csv', Affiliation='University B')]
    assert rank_records(rows, [ResearchIdea('vision')])[0].candidate_count == 2


def test_duplicate_supervisor_rows_and_transitive_copy_groups_keep_all_records():
    rows = [record('Alex', 'vision', 'a.csv', 'a1'), record('Alex', 'sensors', 'a.csv', 'a2'),
            record('Alex', 'wireless', 'b.csv', 'b1'), record('Alex', 'sensors', 'b.csv', 'b2')]
    result = rank_records(rows, [ResearchIdea('vision sensors')])[0]
    assert result.candidate_count == 1
    assert result.matches[0].record_ids == ('a1', 'a2', 'b1', 'b2')


def test_matching_email_groups_rows_with_name_uncertainty():
    rows = [record('Alex', 'vision', 'a.csv', Email='alex@example.test'),
            record('A. Example', 'sensors', 'b.csv', Email='alex@example.test')]
    result = rank_records(rows, [ResearchIdea('vision sensors')])[0]
    assert result.candidate_count == 1
    assert any('different names' in warning for warning in result.matches[0].uncertainties)


def test_weighted_keyword_coverage_and_boundaries():
    idea = ResearchIdea('unrelated', keywords=('vision', 'sensors', 'AI'), keyword_weights={'vision': 2})
    rows = [record('Vision', 'computer vision chair'), record('Sensors', 'sensors')]
    result = rank_records(rows, [idea], RankingConfig(text_weight=0, keyword_weight=1))[0]
    assert result.matches[0].supervisor_name == 'Vision'
    assert result.matches[0].score == 0.5
    assert result.matches[1].score == 0.25
    assert 'AI' not in result.matches[0].matched_terms
    assert any('correlated' in warning for warning in result.matches[0].uncertainties)


def test_domain_component_uses_structured_fields_only():
    idea = ResearchIdea('vision', domain='computer science')
    rows = [record('Structured', 'vision', Domain='Computer Science'),
            record('Unstructured', 'computer science vision')]
    result = rank_records(rows, [idea], RankingConfig(text_weight=0, domain_weight=1))[0]
    assert result.matches[0].supervisor_name == 'Structured'
    assert result.matches[0].score == 1
    assert result.matches[1].score == 0
    assert any('domain field' in warning for warning in result.matches[1].uncertainties)


def test_missing_optional_inputs_remain_zero_without_hidden_renormalization():
    result = rank_records([record('A', 'vision')], [ResearchIdea('vision')],
                          RankingConfig(text_weight=1, keyword_weight=1, domain_weight=1))[0]
    assert result.matches[0].score == pytest.approx(1 / 3, abs=1e-6)
    assert len(result.warnings) >= 3
    zero = rank_records([record('A', 'vision')],
        [ResearchIdea('vision', keywords=('vision',), keyword_weights={'vision': 0})],
        RankingConfig(text_weight=0, keyword_weight=1))[0]
    assert zero.matches[0].score == 0
    assert any('positively weighted' in text for text in zero.matches[0].uncertainties)


def test_reproducible_under_reordering(records):
    idea = ResearchIdea('vision sensors')
    assert rank_records(records, [idea]) == rank_records(list(reversed(records)), [idea])
    assert rank_records(records, [idea]) == rank_records(records, [idea])


def test_configurable_fields():
    row = replace(record('ignored', 'ignored'), fields={'Academic': 'A', 'Skills': ['vision', 'sensors']})
    result = rank_records([row], [ResearchIdea('vision sensors')],
        RankingConfig(name_fields=['academic'], expertise_fields=['skills']))[0]
    assert result.matches[0].supervisor_name == 'A'
    assert result.matches[0].score > 0


@pytest.mark.parametrize('config', [RankingConfig(max_records=1), RankingConfig(max_total_chars=10),
                                   RankingConfig(max_chars_per_record=10)])
def test_resource_limits_fail_without_silent_truncation(records, config):
    with pytest.raises(RankingError):
        rank_records(records, [ResearchIdea('vision')], config)


def test_idea_limit_top_k_and_duplicate_selection(records):
    ideas = [ResearchIdea('vision'), ResearchIdea('sensors')]
    with pytest.raises(RankingError):
        rank_records(records, ideas, RankingConfig(max_ideas=1))
    with pytest.raises(RankingError, match='only once'):
        rank_records(records, [ideas[0], ideas[0]])
    assert len(rank_records(records, ideas, RankingConfig(top_k=1))[0].matches) == 1


@pytest.mark.parametrize('kwargs', [{'title': ''}, {'title': 'x', 'keywords': 'vision'},
    {'title': 'x', 'keyword_weights': {'not a keyword': 2}},
    {'title': 'x', 'keywords': ('vision',), 'keyword_weights': {'vision': math.nan}},
    {'title': 'x', 'keywords': ('vision',), 'keyword_weights': {'vision': -1}},
    {'title': 'x', 'keywords': ('vision',), 'keyword_weights': {'vision': True}},
    {'title': 'x', 'idea_id': '../escape'}])
def test_invalid_ideas_rejected(kwargs):
    with pytest.raises(ValueError):
        ResearchIdea(**kwargs)


@pytest.mark.parametrize('kwargs', [{'text_weight': 0}, {'keyword_weight': math.inf},
    {'domain_weight': -1}, {'max_features': 0}, {'max_ideas': True}, {'name_fields': 'name'}])
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        RankingConfig(**kwargs)


def test_saved_idea_lifecycle_is_local_and_non_destructive(store):
    idea = ResearchIdea('  Vision  ', 'description', ('Vision', 'vision', 'Sensors'),
                        'Science', {'vision': 2})
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        store.add_idea(idea)
        reopened = RecordStore(store.root)
        assert reopened.list_ideas() == [idea]
        edited = replace(idea, title="Vision'; DROP TABLE records; --", description='new description')
        reopened.update_idea(edited)
        assert reopened.list_ideas() == [edited]
        with pytest.raises(StorageError, match='already exists'):
            reopened.add_idea(edited)
        reopened.archive_idea(idea.idea_id)
        assert not reopened.list_ideas()
        assert reopened.count() == 0
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('SELECT archived FROM ideas').fetchone()[0] == 1
        assert connection.execute('SELECT description FROM ideas').fetchone()[0] == 'new description'
    with pytest.raises(StorageError):
        store.update_idea(edited)
    with pytest.raises(StorageError):
        store.archive_idea(edited.idea_id)


def _downgrade_to_v1(store):
    with sqlite3.connect(store.path) as connection:
        connection.execute('DROP TABLE ideas')
        connection.execute('PRAGMA user_version=1')


def test_v1_migration_preserves_records_and_manifests(store, tmp_path):
    from handlers.local import import_document
    path = tmp_path / 'notes.txt'
    path.write_text('vision research')
    imported = import_document(path)
    store.save_import(imported)
    with sqlite3.connect(store.path) as connection:
        before_records = connection.execute('SELECT * FROM records').fetchall()
        before_imports = connection.execute('SELECT * FROM imports').fetchall()
    _downgrade_to_v1(store)
    reopened = RecordStore(store.root)
    reopened.add_idea(ResearchIdea('vision'))
    assert reopened.save_import(imported).duplicates == 1
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('SELECT * FROM records').fetchall() == before_records
        assert connection.execute('SELECT * FROM imports').fetchall() == before_imports
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 2


def test_failed_migration_rolls_back_schema_and_version(store):
    _downgrade_to_v1(store)
    original = RecordStore._create_ideas_table
    def fail(connection):
        original(connection)
        raise sqlite3.OperationalError('simulated migration failure')
    with patch.object(RecordStore, '_create_ideas_table', side_effect=fail):
        with pytest.raises(StorageError):
            RecordStore(store.root)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='ideas'").fetchone()
    assert RecordStore(store.root).list_ideas() == []


def test_spoofed_incomplete_schema_is_not_migrated(store):
    _downgrade_to_v1(store)
    with sqlite3.connect(store.path) as connection:
        connection.execute('DROP TABLE imports')
    before = store.path.read_bytes()
    with pytest.raises(StorageError, match='layout'):
        RecordStore(store.root)
    assert store.path.read_bytes() == before


def test_ranking_never_opens_network(records):
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        assert rank_records(records, [ResearchIdea('vision')])[0].matches


def test_ranker_import_is_lightweight():
    code = 'import rank.supervisor_ranker,sys; assert not any(x in sys.modules for x in ("numpy","sklearn","torch","sentence_transformers"))'
    subprocess.run([sys.executable, '-B', '-c', code], check=True)


def test_configuration_loaded():
    config = load_config()
    assert config.ranking.text_weight == 1
    assert config.ranking_offline_only


def test_idea_menu_create_edit_remove(store, monkeypatch, capsys):
    from ui import ideas, menu
    actions = iter(['Create idea', 'List ideas', 'Edit idea', 'Remove idea', 'Back'])
    entries = iter(['Vision', 'computer vision', 'vision,sensors', 'Science', '{"vision":2}',
                    'Vision revised', '', '', '', ''])
    def choose(message, choices):
        return choices[0] if message == 'Research idea:' else next(actions)
    monkeypatch.setattr(menu, 'prompt_choice', choose)
    monkeypatch.setattr(menu, 'prompt_text', lambda _: next(entries))
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    ideas.run(store, RankingConfig())
    output = capsys.readouterr().out
    assert 'saved locally' in output
    assert 'Research idea updated' in output
    assert 'removed from the active list' in output
    assert not store.list_ideas()
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('SELECT title, archived FROM ideas').fetchone() == ('Vision revised', 1)


def test_import_save_compare_export_end_to_end(store, tmp_path, monkeypatch, capsys):
    from handlers.local import import_document
    from ui import ideas, menu
    path = tmp_path / 'supervisors.csv'
    path.write_text('Name,Expertise\nVision researcher,computer vision sensors\nWireless researcher,wireless csi\n')
    store.save_import(import_document(path))
    store.add_idea(ResearchIdea('Vision', 'computer vision sensors'))
    store.add_idea(ResearchIdea('Wireless', 'wireless csi'))
    actions = iter(['Compare ideas', 'Back'])
    entries = iter(['', '', 'csv', 'ranking.json'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *_: next(actions))
    monkeypatch.setattr(menu, 'prompt_multiple', lambda _, choices: choices)
    monkeypatch.setattr(menu, 'prompt_text', lambda _: next(entries))
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    with patch('socket.socket', side_effect=AssertionError('network forbidden')):
        ideas.run(RecordStore(store.root), RankingConfig())
    output = capsys.readouterr().out
    assert SCORE_NOTICE in output
    assert 'Source:' in output
    assert 'Matched terms:' in output
    assert 'Uncertainty:' in output
    data = json.loads((store.root / 'ranking.json').read_text())
    assert len(data['rankings']) == 2
    assert data['rankings'][0]['matches'][0]['supervisor_name'] == 'Vision researcher'
    assert data['rankings'][1]['matches'][0]['supervisor_name'] == 'Wireless researcher'
    assert data['weights']['text'] == 1
    assert (store.root / 'ranking.json').stat().st_mode & 0o077 == 0
    assert store.count() == 2


def test_comparison_export_never_overwrites(store, records, monkeypatch, capsys):
    from core.models import ImportResult
    from ui import ideas, menu
    store.save_import(ImportResult('fixture.csv', records, []))
    store.add_idea(ResearchIdea('vision'))
    existing = store.root / 'keep.json'
    existing.write_bytes(b'original content')
    choices = iter(['Compare ideas', 'Back'])
    entries = iter(['', '', '', 'keep.json'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *_: next(choices))
    monkeypatch.setattr(menu, 'prompt_multiple', lambda _, options: options)
    monkeypatch.setattr(menu, 'prompt_text', lambda _: next(entries))
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    ideas.run(store, RankingConfig())
    assert existing.read_bytes() == b'original content'
    assert 'already exists' in capsys.readouterr().out
    assert not list(store.root.glob('.export-*'))


def test_ranking_main_menu_entry(store, monkeypatch, capsys):
    import argparse
    import spiderdeck
    from core.config import AppConfig, CrawlConfig, OutputConfig
    from fx import effects
    from ui import menu
    monkeypatch.setattr('core.config.load_config', lambda: AppConfig(CrawlConfig(), OutputConfig(str(store.root))))
    choices = iter(['5) Ranking', '8) Quit'])
    monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
    monkeypatch.setattr(menu, 'prompt_choice', lambda *_: 'Back')
    monkeypatch.setattr(spiderdeck, 'run_security_check', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **_: None)
    monkeypatch.setattr(effects, 'glitch_title', lambda *_, **__: None)
    spiderdeck.run_menu(argparse.Namespace(no_fx=True, dry_run=False))
    assert 'Goodbye' in capsys.readouterr().out


def test_nested_expertise_lists_do_not_exhaust_python_recursion():
    nested = 'vision'
    for _ in range(600):
        nested = [nested]
    row = replace(record('A', 'vision'), fields={'Name': 'A', 'Expertise': nested})
    result = rank_records([row], [ResearchIdea('vision')])[0]
    assert result.matches[0].score > 0


def test_invalid_keyword_weights_have_actionable_ui_error(store, monkeypatch, capsys):
    from ui import ideas, menu
    actions = iter(['Create idea', 'Back'])
    entries = iter(['Vision', 'description', 'vision', '', '{invalid personal data'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *_: next(actions))
    monkeypatch.setattr(menu, 'prompt_text', lambda _: next(entries))
    ideas.run(store, RankingConfig())
    output = capsys.readouterr().out
    assert 'valid JSON object' in output
    assert 'personal data' not in output
    assert not store.list_ideas()


def test_corrupt_stored_keywords_fail_without_leaking_contents(store):
    idea = ResearchIdea('Vision')
    store.add_idea(idea)
    with sqlite3.connect(store.path) as connection:
        connection.execute('UPDATE ideas SET keywords_json=?', ('"PRIVATE_CONTENT"',))
    with pytest.raises(StorageError, match='malformed') as caught:
        store.list_ideas()
    assert 'PRIVATE_CONTENT' not in str(caught.value)


def test_huge_numeric_weights_and_invalid_unicode_rejected():
    with pytest.raises(ValueError):
        ResearchIdea('Vision', keywords=('vision',), keyword_weights={'vision': 10 ** 400})
    with pytest.raises(ValueError):
        RankingConfig(text_weight=10 ** 400)
    with pytest.raises(ValueError, match='UTF-8'):
        ResearchIdea('Invalid \ud800 title')


def test_example_ideas_are_valid_editable_data():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'examples' / 'research_ideas.json'
    ideas = [ResearchIdea(**entry) for entry in json.loads(path.read_text(encoding='utf-8'))]
    assert len(ideas) == 4
    assert all(idea.description and idea.keywords for idea in ideas)
