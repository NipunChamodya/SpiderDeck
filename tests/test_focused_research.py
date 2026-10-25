"""Focused frontier and conditional collection stay inside the original policy."""
import json
import socket
from dataclasses import replace

import pytest

from core.config import CrawlConfig
from core.storage import RecordStore
from crawler.collector import Collector
from crawler.frontier import TopicFrontier
from research.cache import ResearchCache
from research.models import ResearchProject
from research.relevance import ResearchProfile
from research.storage import ProjectStore
from security.network_policy import approve_target
from tests.test_collection import Clock, ScriptTransport, response, ORIGIN


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))])


def collect(routes, project=None, cache=None, **options):
    routes={'/robots.txt':response('User-agent: *\nAllow: /',media='text/plain'),**routes}
    transport,clock=ScriptTransport(routes),Clock()
    config=CrawlConfig(allowed_domains=['research.test'],**options)
    crawler=Collector(approve_target(ORIGIN,config.allowed_domains,authorized=True),config,
        transport=transport,clock=clock,sleep=clock.sleep,
        profile=ResearchProfile(project) if project else None,cache=cache)
    return crawler.run(),transport


def project(mode='balanced'):
    return ResearchProject('Phishing detection WebAssembly',keywords=('phishing','WebAssembly'),mode=mode)


def test_topic_links_prioritized_over_sports_and_external_not_authorized():
    routes={'/':response('<article><h1>Phishing WebAssembly</h1><p>phishing WebAssembly</p>'
        '<a href="/aaa-sports">sports</a><a href="/zzz-phishing-webassembly">phishing WebAssembly</a>'
        '<a href="https://external.test/phishing">WebAssembly</a></article>'),
        '/aaa-sports':response('<p>sport</p>'),
        '/zzz-phishing-webassembly':response('<h1>Phishing WebAssembly</h1><p>phishing WebAssembly</p>')}
    report,transport=collect(routes,project(),max_pages=2)
    assert transport.calls[-1][0].endswith('/zzz-phishing-webassembly')
    assert len(report.documents)==2
    assert all('external.test' not in url for url,_ in transport.calls)
    assert report.stop_reason=='page_limit'


@pytest.mark.parametrize('mode,expected', [('strict',1),('balanced',2),('discovery',3)])
def test_modes_limit_low_relevance_navigation(mode,expected):
    routes={'/':response('<p>Navigation</p><a href="/directory">index</a>'),
            '/directory':response('<p>Directory</p><a href="/another">index</a>'),
            '/another':response('<p>Third directory</p>')}
    report,_=collect(routes,project(mode),max_depth=5)
    assert report.pages_visited==expected
    assert not report.documents
    assert report.low_relevance_pages==expected


def test_frontier_bound_dedup_ties_and_topic_score():
    queue=TopicFrontier(2)
    assert queue.append(('https://r.test/b',1),10)
    assert queue.append(('https://r.test/a',1),10)
    assert not queue.append(('https://r.test/a',1),100)
    assert not queue.append(('https://r.test/c',1),100)
    assert queue.popleft()[0].endswith('/a')
    assert queue.popleft()[0].endswith('/b')
    assert len(queue)==0


def test_conditional_304_reuses_records_without_following_nofollow(tmp_path):
    records=RecordStore(tmp_path/'output');api=ProjectStore(records);p=project();api.create(p)
    cache=ResearchCache(records)
    body='<article><h1>Phishing WebAssembly</h1><p>phishing WebAssembly</p><a rel="nofollow" href="/forbidden">more</a></article>'
    first,_=collect({'/':response(body,etag='"v1"')},p,cache)
    api.ingest(p,first.documents[0]);cache.remember(first.documents[0],first.cache_validators[ORIGIN+'/'])
    second,transport=collect({'/':response(status=304)},p,cache)
    assert second.unchanged_pages==1
    assert len(second.documents)==1
    assert len(transport.calls)==2
    assert transport.calls[1][1]['conditional_headers']=={'If-None-Match':'"v1"'}
    summary=api.ingest(p,second.documents[0]);assert summary.inserted==0 and summary.duplicates==1
    assert records.count()==1


def test_304_does_not_override_new_robots_or_metadata_restriction(tmp_path):
    records=RecordStore(tmp_path/'output');api=ProjectStore(records);p=project();api.create(p);cache=ResearchCache(records)
    first,_=collect({'/':response('<p>phishing WebAssembly</p>',etag='"v1"')},p,cache)
    api.ingest(p,first.documents[0]);cache.remember(first.documents[0],first.cache_validators[ORIGIN+'/'])
    report,transport=collect({'/robots.txt':response('User-agent: *\nDisallow: /',media='text/plain'),
                              '/':response(status=304)},p,cache)
    assert report.stop_reason=='robots_disallow' and len(transport.calls)==1
    report,_=collect({'/':response(status=304,**{'x-robots-tag':'noarchive'})},p,cache)
    assert report.stop_reason=='page_robots_restriction' and not report.documents


def test_cache_reuse_still_validates_dns(tmp_path,monkeypatch):
    records=RecordStore(tmp_path/'output');api=ProjectStore(records);p=project();api.create(p);cache=ResearchCache(records)
    first,_=collect({'/':response('<p>phishing WebAssembly</p>',etag='"v1"')},p,cache)
    api.ingest(p,first.documents[0]);cache.remember(first.documents[0],first.cache_validators[ORIGIN+'/'])
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    report,transport=collect({'/':response(status=304)},p,cache)
    assert report.stop_reason=='prohibited_destination' and not transport.calls


def test_focus_resource_limits_remain_effective():
    report,transport=collect({'/':response('<p>phishing WebAssembly</p><a href="/next">phishing</a>')},project(),max_pages=1)
    assert len(transport.calls)==2 and report.pages_visited==1
    report,_=collect({'/':response('<p>phishing WebAssembly</p>')},project(),max_requests=1)
    assert report.stop_reason=='request_limit'


def test_conditional_headers_cannot_smuggle_credentials_or_newlines(monkeypatch):
    from crawler.fetcher import PinnedTransport
    from security.network_policy import NetworkPolicy,CollectionError
    config=CrawlConfig(allowed_domains=['research.test'])
    policy=NetworkPolicy(approve_target(ORIGIN,config.allowed_domains,authorized=True),config.allowed_domains)
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('invalid headers reached DNS'))
    for headers in ({'Cookie':'secret'},{'Authorization':'secret'},{'If-None-Match':'x\r\nCookie: secret'}):
        with pytest.raises(CollectionError,match='cache_validation_failed'):
            PinnedTransport().request(ORIGIN,policy,user_agent='SpiderDeckBot/0.1',timeout=1,max_bytes=100,conditional_headers=headers)


def test_focused_collection_cancellation_is_bounded():
    from security.network_policy import CollectionError
    report,transport=collect({'/':CollectionError('request_timeout')},project(),max_retries=0)
    assert report.stop_reason=='request_timeout' and report.failed_pages==1
    assert len(transport.calls)==2


def test_review_not_reported_as_strong_relevance():
    p=replace(project('strict'),settings={'max_scoring_chars':1000})
    report,_=collect({'/':response('<p>'+('unrelated '*300)+'</p>')},p)
    assert report.review_pages==1 and report.relevant_pages==0


def test_oversized_html_base_cannot_expand_frontier_memory():
    body='<base href="https://research.test/'+('x'*5000)+'"><p>Phishing WebAssembly</p>'+('<a href="#f">more</a>'*2000)
    report,transport=collect({'/':response(body)},project())
    assert len(transport.calls)==2 and report.links_discovered==0


def test_nested_html_structure_has_an_aggregate_budget():
    from crawler.collector import extract
    body='<article>'+('<p>'*100)+('phishing WebAssembly '*1000)+('</p>'*100)+'</article>'
    result,_=extract(response(body),max_records=100,max_links=100)
    structure=next(iter(result.details.values()))
    assert sum(len(text) for text in structure['paragraphs'])<=500000
    assert structure['warnings']
