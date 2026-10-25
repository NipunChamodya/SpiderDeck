"""Synthetic research pipeline benchmark; never opens the user's database."""
from __future__ import annotations

import argparse
import json
import resource
import tempfile
import time
import tracemalloc
from pathlib import Path
from uuid import uuid4

from core.config import CrawlConfig
from core.storage import RecordStore, SearchFilters
from crawler.collector import Collector
from crawler.fetcher import Response
from exporters.research import export_project
from handlers.local import import_document
from research.evaluation import evaluate
from research.models import ResearchProject
from research.relevance import ResearchProfile
from research.storage import ProjectStore
from security.filesystem import new_output_text, output_directory, open_output_directory
from security.network_policy import approve_target


def run(output: Path, count: int = 1000, *, compare: bool = False) -> dict:
    if not 1 <= count <= 2000: raise ValueError('Use 1–2000 synthetic records.')
    root=output_directory(output)
    with open_output_directory(root): pass
    measurements={}
    def measured(name, action):
        tracemalloc.start()
        start=time.perf_counter()
        try: result=action()
        finally:
            seconds=time.perf_counter()-start
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        measurements[name]={'seconds':seconds,'python_peak_bytes':peak}
        return result
    with tempfile.TemporaryDirectory(prefix='research-benchmark-',dir=root) as directory:
        work=Path(directory)
        store=RecordStore(work/'data');api=ProjectStore(store)
        project=ResearchProject('Phishing detection using WebAssembly',keywords=('phishing detection','WebAssembly'))
        measured('project_create',lambda:api.create(project))
        source=work/'synthetic.json'
        source.write_text(json.dumps([{'id':n,'text':f'Phishing detection using WebAssembly in a browser. Synthetic item {n} தமிழ் සිංහල.'} for n in range(count)],ensure_ascii=False))
        result=measured('document_extract',lambda:import_document(source))
        profile=ResearchProfile(project)
        measured('relevance',lambda:[profile.score(record.title,record.text) for record in result.records])
        saved=measured('sqlite_project_ingest',lambda:api.ingest(project,result))
        if saved.linked!=count:raise ValueError('Unexpected benchmark association count.')
        measured('project_literal_search',lambda:api.search(project.project_id,SearchFilters('WebAssembly')))
        from dataclasses import replace
        project=replace(api.get(project.project_id),settings={**project.settings,'search_mode':'fts'})
        api.update(project);project=api.get(project.project_id)
        measured('project_fts_or_fallback',lambda:api.search(project.project_id,SearchFilters('WebAssembly')))
        for format in ('md','json','csv'):
            exported=measured('export_'+format,lambda format=format:export_project(api,project,'synthetic.'+format,format))
            if exported!=count:raise ValueError('Unexpected benchmark export count.')
        measured('sqlite_project_reimport',lambda:api.ingest(project,result))
        source.write_text(json.dumps([{'id':n,'text':f'Updated phishing detection WebAssembly implementation {n} தமிழ் සිංහල.'} for n in range(count)],ensure_ascii=False))
        changed=import_document(source)
        versions=measured('sqlite_new_versions',lambda:api.ingest(project,changed))
        if versions.updated!=count:raise ValueError('Version preservation check failed.')
        copy=work/'copy.json';copy.write_bytes(source.read_bytes())
        copied=import_document(copy)
        copy_saved=measured('cross_source_exact_copies',lambda:api.ingest(project,copied))
        if copy_saved.content_duplicates!=count:raise ValueError('Exact copy preservation failed.')
        # Static in-memory HTTP fixtures with real Collector policy checks.
        # DNS/transport latency is intentionally excluded, not reported as live throughput.
        class Transport:
            def request(self,url,policy,**kwargs):
                policy.check_url(url)
                return Response(url,200,{'content-type':'text/plain' if url.endswith('/robots.txt') else 'text/html'},
                    b'User-agent: *\nAllow: /' if url.endswith('/robots.txt') else b'<h1>Phishing detection WebAssembly</h1><p>phishing detection WebAssembly</p>')
        clock=[0.0]
        config=CrawlConfig(allowed_domains=['research.test'])
        report=measured('offline_collection',lambda:Collector(approve_target('https://research.test/',config.allowed_domains,authorized=True),
            config,transport=Transport(),profile=profile,clock=lambda:clock[0],sleep=lambda duration:clock.__setitem__(0,clock[0]+duration)).run())
        if len(report.documents)!=1:raise ValueError('Unexpected fixture collection count.')
        with store._connection() as connection:
            fts=api._fts(connection)
            query_plan=[tuple(row) for row in connection.execute('EXPLAIN QUERY PLAN SELECT * FROM project_records WHERE project_id=? ORDER BY score DESC,record_id LIMIT 20',(project.project_id,))]
            version_plan=[tuple(row) for row in connection.execute('EXPLAIN QUERY PLAN SELECT 1 FROM records WHERE source=? AND source_type=? AND metadata_json=? AND record_id<>? LIMIT 1',('source','json','{}','id'))]
            payload_bytes=connection.execute('SELECT sum(length(text)+length(fields_json)) FROM records').fetchone()[0]
            copy_refs=connection.execute('SELECT count(*) FROM record_copies').fetchone()[0]
        fixture=json.loads((Path(__file__).resolve().parents[1]/'tests/fixtures/research_judgments.json').read_text())
        comparison=None
        if compare:
            from research.evaluation import compare_tfidf
            comparison=measured('tfidf_fixture_comparison',lambda:compare_tfidf(fixture))
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        import sys
        import platform,sqlite3,hashlib
        environment={'python':sys.version.split()[0],'system':platform.system(),'machine':platform.machine(),'sqlite':sqlite3.sqlite_version}
        return {'environment':environment,'fixture_sha256':hashlib.sha256(json.dumps(fixture,sort_keys=True).encode()).hexdigest(),'records':count,'measurements':measurements,'fts5_available':fts,'project_query_plan':query_plan,'version_query_plan':version_plan,
                'copy_references':copy_refs,'stored_payload_characters':payload_bytes,'database_bytes':store.path.stat().st_size,'process_rss_bytes':rss if sys.platform=='darwin' else rss*1024,
                'tfidf_comparison':comparison,'evaluation':evaluate(fixture),'notes':'Synthetic, traced actions. Network/GUI excluded. RSS includes setup and native allocations. No general speedup or real-world accuracy claim.'}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records',type=int,default=1000)
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parents[1]/'output')
    parser.add_argument('--compare-tfidf',action='store_true',help='Explicitly benchmark existing scikit-learn TF-IDF on the authored fixture')
    args=parser.parse_args()
    try:
        result=run(args.output_dir,args.records,compare=args.compare_tfidf)
        name='research-performance-'+uuid4().hex+'.json'
        with new_output_text(args.output_dir.resolve(),name) as handle:
            json.dump(result,handle,ensure_ascii=False,indent=2);handle.write('\n')
        print(args.output_dir.resolve()/name)
        return 0
    except (OSError,ValueError,TypeError):
        print('Research benchmark failed. Check the private output directory, dependencies and record limit.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
