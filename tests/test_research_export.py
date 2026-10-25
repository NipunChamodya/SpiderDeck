import csv
import json
from dataclasses import replace

import pytest

from core.models import ImportResult
from core.storage import RecordStore, SearchFilters
from exporters.research import export_project
from handlers.local import import_document
from research.models import ResearchProject
from research.storage import ProjectStore


@pytest.fixture
def evidence(tmp_path):
    store=RecordStore(tmp_path/'output');api=ProjectStore(store)
    project=ResearchProject('Phishing',keywords=('phishing',))
    api.create(project)
    path=tmp_path/'evidence.txt';path.write_text('phishing <script>alert(1)</script> ```\nதமிழ் සිංහල')
    api.ingest(project,import_document(path))
    return api,project,path


@pytest.mark.parametrize('format',['md','json','csv'])
def test_project_exports_readable_complete_and_no_overwrite(evidence,format):
    api,project,path=evidence
    name='findings.'+format
    assert export_project(api,project,name,format)==1
    data=(api.root/name).read_text()
    assert str(path) in data and 'தமிழ்' in data
    if format=='json': assert len(json.loads(data)['records'])==1
    if format=='csv': assert len(list(csv.reader(data.splitlines())))>=2
    if format=='md': assert '````text' in data and 'No generated summary' in data
    with pytest.raises(FileExistsError):export_project(api,project,name,format)
    assert (api.root/name).read_text()==data
    assert export_project(api,project,name,format,overwrite=True)==1
    backup=next(api.root.glob('export-backup-*'))
    assert backup.read_text()==data and backup.stat().st_mode&0o777==0o600


@pytest.mark.parametrize('name',['../escape.json','/tmp/escape.json','folder/escape.json','.hidden.json'])
def test_research_export_traversal_refused(evidence,name):
    api,p,_=evidence
    with pytest.raises(ValueError):export_project(api,p,name,'json',overwrite=True)


def test_project_csv_formula_injection(evidence):
    api,p,path=evidence
    record=import_document(path).records[0]
    record=replace(record,record_id='formula',title='\ufeff=PRIVATE()',text='phishing')
    api.ingest(p,ImportResult(str(path),[record],[]))
    export_project(api,p,'safe.csv','csv')
    with (api.root/'safe.csv').open(newline='') as handle:
        rows=list(csv.DictReader(handle))
    assert next(row for row in rows if row['record_id']=='formula')['title'].startswith("'")


def test_project_unicode_fts_and_date_filtering(evidence):
    api,p,_=evidence
    assert len(api.search(p.project_id,SearchFilters('தமிழ்')))==1
    assert not api.search(p.project_id,since='2999-01-01')
    assert not api.search(p.project_id,until='1900-01-01')
    with pytest.raises(ValueError):api.search(p.project_id,since='bad date')
    api.update(replace(p,settings={**p.settings,'search_mode':'fts'}))
    assert len(api.search(p.project_id,SearchFilters('phishing')))==1
    assert not api.search(p.project_id,SearchFilters('phishing OR anything'))


def test_reassessment_does_not_duplicate_or_remove_shared_evidence(evidence):
    api,p,_=evidence
    changed=replace(p,keywords=('unrelated',));api.update(changed);changed=api.get(p.project_id)
    assert api.reassess(changed)==1
    assert len(api.search(p.project_id))==1
    assert api.search(p.project_id)[0]['analysis']['decision']=='low relevance'
    assert api.records.count()==1


def test_project_export_cannot_replace_symlink_or_hardlink(evidence,tmp_path):
    api,p,_=evidence
    outside=tmp_path/'outside.json';outside.write_text('keep')
    target=api.root/'linked.json';target.symlink_to(outside)
    with pytest.raises(ValueError):export_project(api,p,'linked.json','json',overwrite=True)
    assert outside.read_text()=='keep'
    target.unlink()
    import os
    outside.chmod(0o600);os.link(outside,target)
    with pytest.raises(ValueError):export_project(api,p,'linked.json','json',overwrite=True)
    assert outside.read_text()=='keep'


def test_export_failure_preserves_old_private_file(evidence,monkeypatch):
    api,p,_=evidence
    export_project(api,p,'old.json','json')
    before=(api.root/'old.json').read_bytes()
    def fail(*args,**kwargs):
        yield api.search(p.project_id)[0]
        raise ValueError('fixture failure')
    monkeypatch.setattr(api,'_read_findings',fail)
    with pytest.raises(ValueError):export_project(api,p,'old.json','json',overwrite=True)
    assert (api.root/'old.json').read_bytes()==before
    assert not list(api.root.glob('replacement-*'))


def test_json_records_and_assessment_profiles_share_one_snapshot(evidence,monkeypatch,tmp_path):
    import sqlite3
    api,p,path=evidence
    with sqlite3.connect(api.records.path) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
    original=api._read_profiles
    def profiles(connection,project_id):
        yield from original(connection,project_id)
        # A legitimate second writer can commit under WAL while export is open.
        changed=replace(api.get(p.project_id),description='New assessment profile')
        api.update(changed);changed=api.get(p.project_id)
        other=tmp_path/'later.txt';other.write_text('phishing new research evidence')
        api.ingest(changed,import_document(other))
    monkeypatch.setattr(api,'_read_profiles',profiles)
    assert export_project(api,p,'snapshot.json','json')==1
    data=json.loads((api.root/'snapshot.json').read_text())
    assert data['project']['description']==''
    assert len(data['records'])==1
    assert all(row['analysis']['profile_hash'] in data['assessment_profiles'] for row in data['records'])
    assert len(api.search(p.project_id))==2
