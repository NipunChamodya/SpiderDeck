"""Generated projects, migrations and local evidence; no live network."""
import json
import sqlite3
from dataclasses import replace

import pytest

from core.models import ImportResult
from core.storage import RecordStore, SearchFilters, StorageError, SCHEMA_VERSION
from handlers.local import import_document
from research.models import ResearchProject
from research.relevance import ResearchProfile, suggest_keywords
from research.storage import ProjectStore


@pytest.fixture
def store(tmp_path):
    return RecordStore(tmp_path / 'output')


@pytest.fixture
def document(tmp_path):
    path = tmp_path / 'research.txt'
    path.write_text('Phishing detection uses WebAssembly for browser security. தமிழ் සිංහල')
    return import_document(path)


def project():
    return ResearchProject('Phishing detection using WebAssembly', keywords=('phishing detection', 'WebAssembly'))


def test_project_crud_associations_and_shared_records(store, document):
    api = ProjectStore(store)
    first, second = project(), replace(project(), title='Second research')
    api.create(first)
    api.create(second)
    assert api.ingest(first, document).linked == 1
    assert api.ingest(second, document).inserted == 0
    assert store.count() == 1
    assert api.search(first.project_id)[0]['analysis']['matched'] == ['phishing detection', 'WebAssembly']
    api.update(replace(first, title='Renamed', archived=True))
    assert len(api.list()) == 1
    assert len(api.list(include_archived=True)) == 2
    with pytest.raises(StorageError): api.delete(first.project_id)
    api.delete(first.project_id, confirmed=True)
    assert store.count() == 1
    assert len(api.search(second.project_id)) == 1
    with store._connection() as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_modes_and_explanations_are_deterministic():
    idea = project()
    profile = ResearchProfile(idea)
    exact = profile.score('Phishing detection', 'WebAssembly phishing detection browser security')
    unrelated = profile.score('Sports', 'University sports and games')
    assert exact == profile.score('Phishing detection', 'WebAssembly phishing detection browser security')
    assert exact.score > unrelated.score == 0
    assert exact.decision == 'relevant'
    assert unrelated.missing == idea.keywords
    assert ResearchProfile(replace(idea, mode='strict')).explore(0, 1, 0) is False
    assert profile.explore(0, 1, 0)
    assert not profile.explore(0, 2, 0)
    assert ResearchProfile(replace(idea, mode='discovery')).explore(0, 2, 0)
    assert profile.link_priority('https://research.test/phishing-detection') > profile.link_priority('https://research.test/sports')


def test_unicode_and_bounded_review():
    profile = ResearchProfile(ResearchProject('தமிழ் සිංහල', keywords=('தமிழ்', 'සිංහල')))
    assert len(profile.score('', 'தமிழ் සහ සිංහල').matched) == 2
    result = ResearchProfile(replace(project(), settings={'max_scoring_chars':1000})).score('', 'x '*1000)
    assert result.truncated and result.decision == 'review'
    assert suggest_keywords('Detection using WebAssembly') == ('detection', 'webassembly')


def test_project_search_pagination_exportable_structure_and_coverage(store, tmp_path):
    api = ProjectStore(store)
    p = project(); api.create(p)
    for number in range(3):
        path = tmp_path / f'{number}.txt'; path.write_text('WebAssembly phishing detection')
        api.ingest(p, import_document(path))
    assert len(api.search(p.project_id, SearchFilters('WebAssembly'), limit=2)) == 2
    assert len(api.search(p.project_id, limit=2, offset=2)) == 1
    assert not api.search(p.project_id, SearchFilters("' OR 1=1--"))
    assert api.dashboard(p)['coverage']['WebAssembly']['label'] == 'Moderate'
    assert api.dashboard(p)['exact_duplicates'] == 2


def make_v2(store):
    with sqlite3.connect(store.path) as connection:
        connection.execute('DROP TABLE IF EXISTS research_fts')
        for name in ('project_records','record_copies','research_fts_map','research_profiles','collection_runs','http_cache','research_details','research_sources','projects'):
            connection.execute('DROP TABLE '+name)
        connection.execute('DROP INDEX records_date')
        connection.execute('DROP INDEX records_location')
        connection.execute('PRAGMA user_version=2')


def test_v2_migration_backed_up_and_preserves_records(store, document):
    store.save_import(document)
    make_v2(store)
    reopened = RecordStore(store.root)
    assert reopened.count() == 1
    backups = list(store.root.glob('migration-v2-*.sqlite3'))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM records').fetchone()[0] == 1
    assert ProjectStore(reopened).list() == []


def test_failed_v2_migration_rolls_back(store, document, monkeypatch):
    store.save_import(document); make_v2(store)
    def fail(connection):
        connection.execute('CREATE TABLE temporary_failed_table(value)')
        raise sqlite3.OperationalError('simulated migration failure')
    monkeypatch.setattr('research.schema.create', fail)
    with pytest.raises(StorageError): RecordStore(store.root)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 2
        assert connection.execute('SELECT count(*) FROM records').fetchone()[0] == 1
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='temporary_failed_table'").fetchone()


def test_project_import_collision_is_atomic(store, document):
    api = ProjectStore(store); p = project();api.create(p)
    api.ingest(p, document)
    forged = replace(document.records[0], text='WebAssembly phishing detection altered')
    with pytest.raises(StorageError): api.ingest(p, replace(document, records=[forged]))
    assert store.search()[0].text == document.records[0].text
    assert len(api.search(p.project_id)) == 1


def test_fts_fallback_project_search(tmp_path,monkeypatch):
    monkeypatch.setattr('research.schema.has_fts',lambda conn:False)
    records=RecordStore(tmp_path/'no-fts');api=ProjectStore(records)
    p=replace(project(),settings={'search_mode':'fts'});api.create(p)
    path=tmp_path/'fallback.txt';path.write_text('WebAssembly phishing detection')
    api.ingest(p,import_document(path))
    assert len(api.search(p.project_id,SearchFilters('WebAssembly')))==1


def test_project_settings_validation():
    for kwargs in ({'mode':'unknown'},{'settings':{'strict_threshold':float('nan')}},
                   {'settings':{'discovery_threshold':90}}, {'title':''}):
        with pytest.raises(ValueError):ResearchProject(**{'title':'Research',**kwargs})


def test_labeled_synthetic_relevance_evaluation_is_reproducible():
    from pathlib import Path
    from research.evaluation import evaluate
    fixture=json.loads((Path(__file__).parent/'fixtures/research_judgments.json').read_text())
    result=evaluate(fixture)
    assert result==evaluate(fixture)
    assert result['ranking'][:2]==['exact','implementation']
    assert result['precision_at_k']==pytest.approx(2/3)
    assert 'synthetic' in result['provenance']


def test_shared_assessment_profiles_are_stored_once(store,document):
    api=ProjectStore(store);p=project();api.create(p);api.ingest(p,document)
    second=replace(p,project_id='b'*32);api.create(second);api.ingest(second,document)
    with store._connection() as connection:
        assert connection.execute('SELECT count(*) FROM research_profiles').fetchone()[0]==1
        assert connection.execute('SELECT count(*) FROM project_records').fetchone()[0]==2
        assert connection.execute('SELECT count(*) FROM records').fetchone()[0]==1
    api.delete(p.project_id,confirmed=True)
    assert len(api.search(second.project_id))==1
    api.delete(second.project_id,confirmed=True)
    assert store.count()==1


def test_benchmark_generated_only_and_metrics_valid(tmp_path):
    from benchmarks.research import run
    report=run(tmp_path/'benchmarks',10)
    assert report['records']==10 and report['fts5_available'] in (True,False)
    assert report['measurements']['sqlite_new_versions']['seconds']>0
    assert not list((tmp_path/'benchmarks').glob('research-benchmark-*'))


def test_new_exact_source_copies_share_payload_but_keep_provenance(store,document,tmp_path):
    from core.models import ImportResult
    original=document.records[0];store.save_import(document)
    copied=replace(original,record_id='copied',source='second source',title='Own title')
    store.save_import(ImportResult(copied.source,[copied],[]))
    with store._connection() as conn:
        assert conn.execute('SELECT text FROM records WHERE record_id=?',('copied',)).fetchone()[0]==''
        assert conn.execute('SELECT canonical_id FROM record_copies WHERE record_id=?',('copied',)).fetchone()[0]==original.record_id
    restored=store.search(SearchFilters(source='second source'))[0]
    assert restored.text==original.text and restored.fields==original.fields
    assert restored.source=='second source' and restored.title=='Own title'
    assert store.count(SearchFilters(keyword='தமிழ்'))==2
    assert store.save_import(ImportResult(copied.source,[copied],[])).duplicates==1
    with pytest.raises(StorageError):
        store.save_import(ImportResult(copied.source,[replace(copied,text='altered')],[]))


def test_content_hash_collision_does_not_discard_evidence(store,document,monkeypatch):
    import core.storage
    store.save_import(document)
    with store._connection() as conn:
        digest=conn.execute('SELECT content_hash FROM records').fetchone()[0]
    monkeypatch.setattr(core.storage,'content_hash',lambda record:digest)
    other=replace(document.records[0],record_id='other',text='different text')
    with pytest.raises(StorageError,match='Content hash collision'):
        store.save_import(replace(document,records=[other]))
    assert store.count()==1


def test_legacy_duplicates_survive_migration_unchanged(store,document):
    from core.models import ImportResult
    store.save_import(document)
    copied=replace(document.records[0],record_id='copy',source='second')
    store.save_import(ImportResult('second',[copied],[]))
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE records SET text=?,fields_json=? WHERE record_id=?',
                     (copied.text,json.dumps(copied.fields,ensure_ascii=False,sort_keys=True,separators=(',',':')),'copy'))
        before=conn.execute('SELECT * FROM records ORDER BY record_id').fetchall()
    make_v2(store)
    reopened=RecordStore(store.root)
    with reopened._connection() as conn:
        assert conn.execute('SELECT * FROM records ORDER BY record_id').fetchall()!=[]
        assert [tuple(row) for row in conn.execute('SELECT * FROM records ORDER BY record_id')]==before
        assert conn.execute('SELECT count(*) FROM record_copies').fetchone()[0]==0
    assert len(reopened.search(SearchFilters(keyword='WebAssembly')))==2


def test_history_does_not_store_sensitive_summary_keys(store):
    api=ProjectStore(store);p=project();api.create(p)
    api.record_run(p.project_id,'https://research.test/','completed',{'new_records':2,'PRIVATE_TOKEN':123,'body':'PRIVATE'})
    history=api.history(p.project_id)
    assert json.loads(history[0]['summary_json'])=={'new_records':2}


def test_existing_supervisor_ideas_survive_schema2_upgrade(store,document):
    from rank.models import ResearchIdea
    idea=ResearchIdea('Existing idea',description='preserve this description',keywords=('phishing',))
    store.add_idea(idea);store.save_import(document)
    make_v2(store)
    upgraded=RecordStore(store.root)
    assert upgraded.list_ideas()==[idea]
    assert upgraded.search()[0].to_dict()==document.records[0].to_dict()


def test_title_only_does_not_substitute_for_body_evidence():
    profile=ResearchProfile(ResearchProject('Phishing WebAssembly',keywords=('phishing','WebAssembly')))
    result=profile.score('Phishing WebAssembly','Unrelated sports content')
    assert result.components['title']==1
    assert result.components['coverage']==0
    assert result.decision=='low relevance'


def test_fts_is_contentless_and_math_whitespace_preserved(store,document):
    from processing.content import normalize,describe
    api=ProjectStore(store);p=project();api.create(p);api.ingest(p,document)
    with store._connection() as connection:
        if api._fts(connection):
            assert connection.execute('SELECT text FROM research_fts LIMIT 1').fetchone()[0] is None
    text='x  + y = 2\n\nශ්‍රී\n\nශ්‍රී'
    assert normalize(text)[0]==text
    detail=describe(replace(document.records[0],text=text))
    assert detail['duplicate_paragraphs']==1
    assert detail['cleaned_text']==text


def test_explicit_tfidf_fixture_comparison():
    from pathlib import Path
    from research.evaluation import compare_tfidf
    fixture=json.loads((Path(__file__).parent/'fixtures/research_judgments.json').read_text())
    result=compare_tfidf(fixture)
    assert 0<=result['precision_at_k']<=1 and 0<=result['ndcg_at_k']<=1
    assert set(result['ranking'])=={row['id'] for row in fixture['documents']}
    assert all(0<=score<=1.0000001 for score in result['scores'].values())
