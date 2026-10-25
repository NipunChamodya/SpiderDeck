"""Offline HTTP wire fixtures; no live DNS, sockets or external targets."""
import io
import json
import socket
import ssl
from collections import deque
from dataclasses import replace
from unittest.mock import patch

import pytest

from core.config import CrawlConfig
from core.storage import RecordStore, SearchFilters
from crawler.collector import Collector, extract
from crawler.fetcher import PinnedTransport, Response, _PinnedConnection
from crawler.robots import RobotsRules
from security.network_policy import (
    CollectionError, NetworkPolicy, approve_target, normalize_url, public_ip,
)

ORIGIN = 'https://research.test'
PUBLIC = '8.8.8.8'


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC, port))])


def approval():
    return approve_target(ORIGIN + '/', ['research.test'], authorized=True)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class ScriptTransport:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
    def request(self, url, policy, **kwargs):
        policy.resolve(url)
        self.calls.append((url, kwargs))
        value = self.routes[urlsplit_path(url)]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, CollectionError):
            raise value
        return replace(value, url=url)


def urlsplit_path(url):
    from urllib.parse import urlsplit
    return urlsplit(url).path


def response(body='', status=200, media='text/html', **headers):
    return Response('', status, {'content-type': media, **headers}, body.encode('utf-8'))


def collect(routes, **kwargs):
    routes = {'/robots.txt': response('User-agent: *\nAllow: /', media='text/plain'), **routes}
    transport = ScriptTransport(routes)
    clock = Clock()
    config = CrawlConfig(allowed_domains=['research.test'], **kwargs)
    report = Collector(approval(), config, transport=transport, clock=clock, sleep=clock.sleep).run()
    return report, transport, clock


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'ftp://research.test', 'https://user:SECRET@research.test/',
    'https://research.test:0/', 'https://research.test:8443/', 'https://research.test./',
    'https://research.test\\@127.0.0.1/', 'https://research.test/%2e%2e/private',
    'https://research.test/%2fprivate', 'https://research.test/%252fprivate',
    'https://research.test/%0d%0aHeader', 'https://research.test/%ZZ',
    'https://research.test/?token=SECRET', 'https://research.test/\n',
    'http://[::1]/', 'http://[::ffff:127.0.0.1]/',
])
def test_ambiguous_and_unsupported_urls_refused(url):
    with pytest.raises(CollectionError):
        normalize_url(url)


def test_url_canonicalization_preserves_reserved_octets():
    assert normalize_url('HTTPS://RESEARCH.TEST:443/%7e/%3f/#fragment') == ORIGIN + '/~/%3F/'
    assert normalize_url(ORIGIN + '/தமிழ்') == ORIGIN + '/%E0%AE%A4%E0%AE%AE%E0%AE%BF%E0%AE%B4%E0%AF%8D'


def test_allowlist_and_separate_target_approval_before_dns():
    with patch('socket.getaddrinfo', side_effect=AssertionError('DNS before consent')):
        with pytest.raises(CollectionError, match='target_approval_required'):
            approve_target(ORIGIN, ['research.test'], authorized=False)
        with pytest.raises(CollectionError, match='domain_not_allowlisted'):
            approve_target(ORIGIN, [], authorized=True)
        with pytest.raises(CollectionError):
            approve_target('https://sub.research.test/', ['research.test'], authorized=True)
    policy = NetworkPolicy(approval(), ['research.test', 'other.test'])
    for url in ['https://other.test/', 'http://research.test/', 'https://sub.research.test/']:
        with pytest.raises(CollectionError, match='new_origin_requires_approval'):
            policy.check_url(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '0.0.0.0', '10.0.0.1', '192.168.1.2',
    '169.254.169.254', '100.64.0.1', '224.0.0.1', '::1', '::', 'fc00::1', 'fe80::1',
    '::ffff:8.8.8.8', '2002:0808:0808::1', '2001:0::1', 'ff02::1', 'fe80::1%en0'])
def test_all_nonpublic_and_transition_addresses_blocked(address):
    with pytest.raises(CollectionError):
        public_ip(address)


def test_mixed_dns_results_fail_closed(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC, 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443, 0, 0))])
    with pytest.raises(CollectionError, match='prohibited_destination'):
        NetworkPolicy(approval(), ['research.test']).resolve(ORIGIN)


def test_unresolved_dns_fails_closed(monkeypatch):
    def fail(*a, **kw):
        raise socket.gaierror('SECRET resolver detail')
    monkeypatch.setattr(socket, 'getaddrinfo', fail)
    with pytest.raises(CollectionError) as caught:
        NetworkPolicy(approval(), ['research.test']).resolve(ORIGIN)
    assert str(caught.value) == 'dns_resolution_failed'


class WireSocket:
    def __init__(self, payload, address=PUBLIC):
        self.payload = payload
        self.address = address
        self.connected = None
        self.sent = b''
        self.closed = False
        self.timeouts = []
    def settimeout(self, timeout):
        self.timeouts.append(timeout)
    def connect(self, endpoint):
        self.connected = endpoint
    def getpeername(self):
        return self.address, 443
    def makefile(self, *args):
        return io.BytesIO(self.payload)
    def sendall(self, data):
        self.sent += data
    def close(self):
        self.closed = True
    def shutdown(self, how):
        self.closed = True


def wire(body=b'<p>hello</p>', headers=b'', status=b'200 OK'):
    return b'HTTP/1.1 ' + status + b'\r\nContent-Type: text/html\r\n' + headers + b'\r\n' + body


@pytest.fixture
def sockets(monkeypatch):
    made = []
    pending = deque()
    def factory(*args, **kwargs):
        sock = WireSocket(pending.popleft())
        made.append(sock)
        return sock
    monkeypatch.setattr(socket, 'socket', factory)
    def wrap(context, sock, *, server_hostname, **kwargs):
        assert context.check_hostname
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert server_hostname == 'research.test'
        return sock
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', wrap)
    return pending, made


def request(transport=None, **kwargs):
    return (transport or PinnedTransport()).request(ORIGIN + '/', NetworkPolicy(approval(), ['research.test']),
        user_agent='SpiderDeckBot/0.1', timeout=2, max_bytes=kwargs.get('max_bytes', 10000))


def test_wire_transport_pins_ip_keeps_host_tls_and_ignores_proxies(sockets, monkeypatch):
    pending, made = sockets
    pending.append(wire())
    monkeypatch.setenv('HTTPS_PROXY', 'http://SECRET@127.0.0.1:9999')
    assert request().body == b'<p>hello</p>'
    assert made[0].connected == (PUBLIC, 443)
    assert b'Host: research.test\r\n' in made[0].sent
    assert b'SpiderDeckBot/0.1' in made[0].sent
    assert b'Authorization:' not in made[0].sent
    assert b'Cookie:' not in made[0].sent
    assert b'SECRET' not in made[0].sent
    assert made[0].closed


def test_dns_rebinding_has_no_second_lookup_during_connect(sockets, monkeypatch):
    pending, made = sockets
    pending.append(wire())
    calls = []
    def changing_dns(*a, **kw):
        calls.append(a)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC if len(calls) == 1 else '127.0.0.1', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', changing_dns)
    request()
    assert len(calls) == 1
    assert made[0].connected[0] == PUBLIC
    with pytest.raises(CollectionError, match='prohibited_destination'):
        request()
    assert len(made) == 1


def test_peer_mismatch_never_sends_request(sockets):
    _, made = sockets
    wrong = WireSocket(wire(), address='1.1.1.1')
    with patch('socket.socket', return_value=wrong):
        with pytest.raises(CollectionError, match='peer_address_mismatch'):
            request()
    assert not wrong.sent
    assert wrong.closed


def test_tls_verification_failure_not_downgraded(sockets, monkeypatch):
    pending, made = sockets
    pending.append(wire())
    def fail(*a, **kw):
        raise ssl.SSLCertVerificationError('SECRET cert detail')
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', fail)
    with pytest.raises(CollectionError) as caught:
        request()
    assert str(caught.value) == 'tls_verification_failed'
    assert not made[0].sent


@pytest.mark.parametrize('payload,code', [
    (wire(b'12345', b'Content-Length: 5\r\n'), 'response_too_large'),
    (wire(b'12345'), 'response_too_large'),
    (wire(b'abc', b'Content-Encoding: gzip\r\n'), 'compressed_response_unsupported'),
    (wire(b'abc', b'Content-Length: 3\r\nContent-Length: 3\r\n'), 'ambiguous_response_headers'),
    (wire(b'abc', b'Content-Length: 3\r\nTransfer-Encoding: chunked\r\n'), 'ambiguous_response_headers'),
    (wire(b'', b'X-Long: ' + b'x' * 66000 + b'\r\n'), 'response_headers_too_large'),
    (wire(b'ab', b'Content-Length: 3\r\n'), 'incomplete_response'),
])
def test_wire_bounds_and_headers(sockets, payload, code):
    pending, _ = sockets
    pending.append(payload)
    with pytest.raises(CollectionError, match=code):
        request(max_bytes=4)


def test_denied_response_body_not_read(sockets):
    pending, _ = sockets
    pending.append(wire(b'SECRET', b'Content-Length: 999999\r\n', b'403 Forbidden'))
    result = request(max_bytes=1)
    assert result.status == 403
    assert result.body == b''


@pytest.mark.parametrize('path,allowed', [('/private/a', False), ('/private/open', True),
    ('/private/open/extra', False), ('/free', True), ('/tmp/a/file', False)])
def test_robots_longest_allow_ties_wildcards_and_anchor(path, allowed):
    robots = RobotsRules('User-agent: *\nDisallow: /private/*\nAllow: /private/open$\nDisallow: /tmp/*/file', 'SpiderDeckBot/0.1')
    assert robots.allows(ORIGIN + path) is allowed
    assert RobotsRules('User-agent: *\nDisallow: /x\nAllow: /x', 'SpiderDeckBot/0.1').allows(ORIGIN + '/x')


def test_robots_specific_groups_merge_and_rate():
    robots = RobotsRules('User-agent: *\nDisallow: /\nUser-agent: SpiderDeckBot\nAllow: /\nCrawl-delay: 3\n'
                         'User-agent: SpiderDeckBot\nDisallow: /private\nRequest-rate: 1/10', 'SpiderDeckBot/0.1')
    assert robots.allows(ORIGIN + '/free')
    assert not robots.allows(ORIGIN + '/private')
    assert robots.delay == 10


def test_robot_block_before_page_request():
    report, transport, _ = collect({'/robots.txt': response('User-agent: *\nDisallow: /', media='text/plain')})
    assert report.stop_reason == 'robots_disallow'
    assert len(transport.calls) == 1
    assert not report.documents


def test_robots_404_allows_and_robots_403_stops():
    report, _, _ = collect({'/robots.txt': response(status=404), '/': response('<p>Research</p>')})
    assert report.stop_reason == 'completed'
    assert len(report.documents) == 1
    report, transport, _ = collect({'/robots.txt': response(status=403)})
    assert report.stop_reason == 'authorization_denied'
    assert len(transport.calls) == 1


def test_wire_fixture_integration_collect_persist_search(sockets, tmp_path):
    pending, made = sockets
    pending.extend([
        b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nUser-agent: *\nAllow: /',
        wire('<title>Research</title><p>தமிழ் computer vision</p><a href="/api">API</a>'.encode()),
        b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n[{"Name":"A","Expertise":"vision"}]',
    ])
    clock = Clock()
    config = CrawlConfig(allowed_domains=['research.test'])
    report = Collector(approval(), config, clock=clock, sleep=clock.sleep).run()
    assert report.stop_reason == 'completed'
    assert len(made) == 3
    assert all(sock.connected == (PUBLIC, 443) for sock in made)
    store = RecordStore(tmp_path / 'output')
    for document in report.documents:
        store.save_import(document)
        assert store.save_import(document).duplicates == len(document.records)
    assert store.count() == 2
    assert store.count(SearchFilters(keyword='தமிழ்')) == 1
    assert store.search(SearchFilters(source_type='web_json'))[0].fields['Name'] == 'A'


def test_frontier_dedup_depth_external_and_no_subresource_fetch():
    report, transport, _ = collect({'/': response('<img src="http://127.0.0.1/SECRET"><script src="/script"></script>'
        '<a href="/next#one">Next</a><a href="/next#two">Again</a><a href="https://other.test/">Other</a>'),
        '/next': response('<a href="/too-deep">deeper</a>')}, max_depth=1)
    assert [urlsplit_path(url) for url, _ in transport.calls] == ['/robots.txt', '/', '/next']
    assert len(report.documents) == 2


@pytest.mark.parametrize('target,reason', [('http://127.0.0.1/private', 'invalid_hostname'),
    ('https://other.test/', 'new_origin_requires_approval'), ('http://research.test/', 'new_origin_requires_approval'),
    ('https://user:SECRET@research.test/', 'userinfo_forbidden')])
def test_redirect_enforcement_before_next_request(target, reason):
    report, transport, _ = collect({'/': response(status=302, location=target)})
    assert report.stop_reason == reason
    assert len(transport.calls) == 2
    assert not report.documents
    assert 'SECRET' not in json.dumps(report.audit())


def test_same_origin_redirect_rechecks_robots_and_deduplicates():
    report, transport, _ = collect({'/': response('<a href="/a">a</a><a href="/b">b</a>'),
        '/a': response(status=302, location='/b'), '/b': response('<p>Accepted</p>')})
    assert len(report.documents) == 2
    assert [urlsplit_path(url) for url, _ in transport.calls].count('/b') == 1
    report, transport, _ = collect({'/robots.txt': response('User-agent: *\nDisallow: /private', media='text/plain'),
        '/': response(status=302, location='/private')})
    assert report.stop_reason == 'robots_disallow'
    assert len(transport.calls) == 2


@pytest.mark.parametrize('body', ['<p>Download is disabled</p>', '<p>Verify you are human</p>',
    '<form><input type="password"></form>', '<p>Security limitations</p>',
    '<meta name="robots" content="noarchive"><p>Research</p>'])
def test_restricted_documents_never_produce_records(body):
    report, transport, _ = collect({'/': response(body)})
    assert report.stop_reason in {'access_restriction_detected', 'page_robots_restriction'}
    assert not report.documents
    assert len(transport.calls) == 2


@pytest.mark.parametrize('status,code', [(401, 'authorization_denied'), (403, 'authorization_denied'),
    (407, 'authorization_denied'), (451, 'authorization_denied'), (429, 'rate_limited')])
def test_permission_failures_never_retry(status, code):
    report, transport, _ = collect({'/': response(status=status)}, max_retries=2)
    assert report.stop_reason == code
    assert len(transport.calls) == 2


def test_retries_exponential_rate_and_request_limits():
    report, transport, clock = collect({'/': [response(status=503), response(status=503), response('<p>OK</p>')]})
    assert report.stop_reason == 'completed'
    assert len(transport.calls) == 4
    assert clock.waits == [1.5, 1.5, 2]
    report, transport, _ = collect({'/': [response(status=503)] * 3}, max_requests=2)
    assert report.stop_reason == 'request_limit'
    assert len(transport.calls) == 2


def test_page_frontier_and_duration_limits():
    report, _, _ = collect({'/': response('<a href="/a">a</a><a href="/b">b</a>')}, max_pages=1)
    assert report.stop_reason == 'page_limit'
    report, transport, _ = collect({'/': response('<a href="/a">a</a>')}, max_frontier=1)
    assert any(event['code'] == 'frontier_limit' for event in report.events)
    assert len(transport.calls) == 2
    report, transport, _ = collect({'/': response('not requested')}, max_duration_seconds=1)
    assert report.stop_reason == 'duration_limit'
    assert len(transport.calls) == 1


@pytest.mark.parametrize('body,media,reason', [('PDF', 'application/pdf', 'unexpected_content_type'),
    ('{broken', 'application/json', 'malformed_json'), ('[{"v":NaN}]', 'application/json', 'malformed_json'),
    ('{"error":"you need permission"}', 'application/json', 'access_restriction_detected')])
def test_unexpected_and_malformed_content_stops(body, media, reason):
    report, _, _ = collect({'/': response(body, media=media)})
    assert report.stop_reason == reason
    assert not report.documents


def test_stable_record_ids_and_bounded_json_records():
    first, _, _ = collect({'/': response('<title>A</title><p>vision</p>')})
    second, _, _ = collect({'/': response('<title>A</title><p>vision</p>')})
    assert first.documents[0].records[0].record_id == second.documents[0].records[0].record_id
    report, _, _ = collect({'/': response('[1,2,3]', media='application/json')}, max_records=2)
    assert report.stop_reason == 'record_limit'
    assert not report.documents


def test_google_sheet_viewer_requires_export_without_network():
    permitted = approve_target('https://docs.google.com/spreadsheets/d/SECRET/edit', ['docs.google.com'], authorized=True)
    transport = ScriptTransport({})
    report = Collector(permitted, CrawlConfig(allowed_domains=['docs.google.com']), transport=transport).run()
    assert report.stop_reason == 'interactive_document_requires_export'
    assert not transport.calls
    assert 'SECRET' not in json.dumps(report.audit())


@pytest.mark.parametrize('kwargs', [{'respect_robots_txt': False}, {'allow_localhost': True},
    {'delay_seconds': 0}, {'timeout_seconds': -1}, {'max_requests': 0}, {'max_retries': -1},
    {'user_agent': 'Mozilla/5.0'}, {'user_agent': 'SpiderDeckBot/1\r\nInjection'}])
def test_unsafe_crawl_configuration_refused(kwargs):
    with pytest.raises(ValueError):
        CrawlConfig(**kwargs)


@pytest.mark.parametrize('address', ['64:ff9b::7f00:1', '64:ff9b:1::a00:1', '::127.0.0.1'])
def test_translation_and_compatible_ipv6_blocked(address):
    with pytest.raises(CollectionError):
        public_ip(address)


def test_global_ipv6_dns_socket_is_pinned(sockets, monkeypatch):
    address = '2606:4700:4700::1111'
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', (address, 443, 0, 0))])
    sock = WireSocket(wire(), address=address)
    with patch('socket.socket', return_value=sock) as factory:
        assert request().status == 200
    assert factory.call_args.args[0] == socket.AF_INET6
    assert sock.connected == (address, 443)


def test_alternative_ipv4_representation_cannot_bypass_resolution(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))])
    for host in ['2130706433', '0x7f000001', '0177.0.0.1', '127.1']:
        with pytest.raises(CollectionError):
            approved = approve_target('http://' + host, [host], authorized=True)
            NetworkPolicy(approved, [host]).resolve(approved.seed_url)


def test_redirect_dns_change_to_private_blocks_before_connect(monkeypatch):
    calls = 0
    def resolve(*a, **kw):
        nonlocal calls
        calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC if calls < 3 else '10.0.0.1', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    report, transport, _ = collect({'/': response(status=302, location='/next')})
    assert report.stop_reason == 'prohibited_destination'
    assert len(transport.calls) == 2


def test_redirect_loops_and_redirect_count_bounded():
    report, transport, _ = collect({'/': response(status=302, location='/a'),
        '/a': response(status=302, location='/')})
    assert report.stop_reason == 'redirect_loop'
    assert len(transport.calls) == 3
    report, _, _ = collect({'/': response(status=302, location='/a')}, max_redirects=0)
    assert report.stop_reason == 'redirect_limit'


def test_robots_delay_applies_to_pages_and_redirects():
    report, transport, clock = collect({'/robots.txt': response('User-agent: *\nCrawl-delay: 4', media='text/plain'),
        '/': response(status=302, location='/next'), '/next': response('<p>OK</p>')})
    assert report.stop_reason == 'completed'
    assert clock.waits == [4, 4]


@pytest.mark.parametrize('robots', [response('<html>login</html>'), response(status=500),
    response('User-agent: *\nCrawl-delay: nan', media='text/plain')])
def test_robots_unavailability_fails_closed(robots):
    report, transport, _ = collect({'/robots.txt': robots})
    assert report.stop_reason in {'invalid_robots_response', 'robots_unavailable', 'invalid_robots_rate'}
    assert len(transport.calls) == 1


def test_total_body_budget_enforced_and_transient_retry_bounded():
    report, transport, _ = collect({'/robots.txt': response(status=404), '/': response('<p>too long</p>')}, max_total_bytes=1)
    assert report.stop_reason == 'response_too_large'
    assert not report.documents
    report, transport, _ = collect({'/': [CollectionError('transport_failed')] * 3})
    assert report.stop_reason == 'transport_failed'
    assert len(transport.calls) == 4


def test_audit_omits_sensitive_paths_bodies_and_headers():
    report, _, _ = collect({'/': response('<p>Public</p><a href="/SECRET_PATH">next</a>'),
        '/SECRET_PATH': response('<p>You need permission SECRET_BODY</p>', **{'set-cookie': 'SESSION=SECRET_COOKIE'})})
    assert report.stop_reason == 'access_restriction_detected'
    assert len(report.documents) == 1
    audit = json.dumps(report.audit())
    assert 'SECRET' not in audit
    assert '/SECRET_PATH' not in audit
    assert report.audit()['pages_collected'] == 1


def test_menu_declined_approval_has_no_network_or_storage(monkeypatch, capsys):
    from ui import collection, menu
    monkeypatch.setattr(menu, 'prompt_url', lambda _: ORIGIN)
    monkeypatch.setattr(menu, 'confirm', lambda _: False)
    with patch('socket.socket', side_effect=AssertionError('network before approval')):
        collection.run(CrawlConfig(allowed_domains=['research.test']), lambda: pytest.fail('store before approval'))
    assert 'no requests made' in capsys.readouterr().out


def test_menu_collects_persists_and_writes_private_audit(tmp_path, monkeypatch, capsys):
    from ui import collection, menu
    store = RecordStore(tmp_path / 'output')
    report, _, _ = collect({'/': response('<p>தமிழ் vision</p><a href="/SECRET">next</a>'),
                            '/SECRET': response(status=403)})
    monkeypatch.setattr(menu, 'prompt_url', lambda _: ORIGIN)
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    with patch('ui.collection.Collector') as factory:
        factory.return_value.run.return_value = report
        collection.run(CrawlConfig(allowed_domains=['research.test']), lambda: store)
    assert store.count() == 1
    audit_files = list(store.root.glob('crawl-audit-*.json'))
    assert len(audit_files) == 1
    audit = json.loads(audit_files[0].read_text())
    assert audit['records_saved'] == 1
    assert audit['stop_reason'] == 'authorization_denied'
    assert 'SECRET' not in audit_files[0].read_text()
    assert audit_files[0].stat().st_mode & 0o077 == 0
    assert 'authorized export' in capsys.readouterr().out


def test_failed_audit_reservation_prevents_network(tmp_path, monkeypatch):
    from ui import collection, menu
    store = RecordStore(tmp_path / 'output')
    monkeypatch.setattr(menu, 'prompt_url', lambda _: ORIGIN)
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    with patch('ui.collection.new_output_text', side_effect=PermissionError), patch('ui.collection.Collector') as factory:
        with pytest.raises(PermissionError):
            collection.run(CrawlConfig(allowed_domains=['research.test']), lambda: store)
        factory.assert_not_called()


def test_main_menu_dry_run_and_failed_selfcheck_disable_network(tmp_path, monkeypatch, capsys):
    import argparse
    import spiderdeck
    from core.config import AppConfig, OutputConfig
    from ui import menu
    from fx import effects
    root = tmp_path / 'output'
    monkeypatch.setattr('core.config.load_config', lambda: AppConfig(CrawlConfig(), OutputConfig(str(root))))
    monkeypatch.setattr(effects, 'matrix_intro', lambda **_: None)
    monkeypatch.setattr(effects, 'glitch_title', lambda *_, **__: None)
    for dry_run in [True, False]:
        choices = iter(['1) Web', '8) Quit'])
        monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
        monkeypatch.setattr(spiderdeck, 'run_security_check', lambda: False)
        with patch('socket.socket', side_effect=AssertionError('network disabled')):
            spiderdeck.run_menu(argparse.Namespace(no_fx=True, dry_run=dry_run))
    assert not root.exists()
    assert 'startup security self-check failed' in capsys.readouterr().out


def test_ssl_key_logging_environment_cannot_write_outside_output(sockets, monkeypatch, tmp_path):
    pending, _ = sockets
    pending.append(wire())
    keylog = tmp_path / 'unexpected-tls-secrets.log'
    monkeypatch.setenv('SSLKEYLOGFILE', str(keylog))
    assert request().status == 200
    assert not keylog.exists()


def test_retry_after_respected_and_unreasonable_delay_stops():
    report, _, clock = collect({'/': [response(status=503, **{'retry-after': '8'}), response('<p>OK</p>')]})
    assert report.stop_reason == 'completed'
    assert clock.waits == [1.5, 8]
    report, transport, _ = collect({'/': response(status=503, **{'retry-after': '999999999999'})})
    assert report.stop_reason == 'retry_after_exceeds_budget'
    assert len(transport.calls) == 2
    report, _, _ = collect({'/': response(status=503, **{'retry-after': 'invalid SECRET'})})
    assert report.stop_reason == 'invalid_retry_after'
    assert 'SECRET' not in json.dumps(report.audit())


def test_script_only_page_requires_authorized_export():
    report, _, _ = collect({'/': response('<html><head><title>Portal</title></head><body>'
        '<script>renderAllPrivateData()</script></body></html>')})
    assert report.stop_reason == 'insufficient_static_text'
    assert not report.documents


def test_external_html_base_does_not_reinterpret_links_as_local():
    report, transport, _ = collect({'/': response('<base href="https://other.test/"><p>Research</p><a href="next">Next</a>')})
    assert report.stop_reason == 'completed'
    assert len(transport.calls) == 2


def test_dns_timeout_consumes_budget_before_any_socket(sockets, monkeypatch):
    _, made = sockets
    values = iter([0, 3])
    monkeypatch.setattr('crawler.fetcher.time.monotonic', lambda: next(values))
    with pytest.raises(CollectionError, match='request_timeout'):
        request()
    assert not made


def test_request_deadline_interrupts_slow_body(sockets, monkeypatch):
    import time
    class SlowFile(io.BytesIO):
        def read1(self, size=-1):
            time.sleep(0.03)
            return super().read1(size)
    pending, made = sockets
    pending.append(wire())
    monkeypatch.setattr(WireSocket, 'makefile', lambda self, *a: SlowFile(self.payload))
    # Avoid measuring local CA loading in this small body-timeout fixture.
    with patch('ssl.SSLContext.load_default_certs'):
        with pytest.raises(CollectionError, match='request_timeout'):
            PinnedTransport().request(ORIGIN, NetworkPolicy(approval(), ['research.test']),
                user_agent='SpiderDeckBot/0.1', timeout=0.01, max_bytes=10000)
    assert made[0].closed


def test_transport_retry_can_select_another_validated_public_address(sockets, monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC, 443))])
    sock = WireSocket(wire())
    with patch('socket.socket', return_value=sock):
        result = PinnedTransport().request(ORIGIN, NetworkPolicy(approval(), ['research.test']),
            user_agent='SpiderDeckBot/0.1', timeout=2, max_bytes=1000, address_index=1)
    assert result.status == 200
    assert sock.connected == (PUBLIC, 443)


def test_http_has_no_tls_downgrade_or_extra_auth(sockets):
    pending, made = sockets
    pending.append(wire())
    permitted = approve_target('http://research.test/', ['research.test'], authorized=True)
    result = PinnedTransport().request(permitted.seed_url, NetworkPolicy(permitted, ['research.test']),
        user_agent='SpiderDeckBot/0.1', timeout=2, max_bytes=1000)
    assert result.status == 200
    assert made[0].connected == (PUBLIC, 80)


def test_discovered_robots_disallow_nofollow_and_action_links_not_requested():
    report, transport, _ = collect({'/robots.txt': response('User-agent: *\nDisallow: /private', media='text/plain'),
        '/': response('<p>Research</p><a href="/private">private</a><a href="/skip" rel="nofollow">skip</a>'
                      '<a href="/logout">logout</a><a href="/okay">okay</a>'), '/okay': response('<p>Fine</p>')})
    assert [urlsplit_path(url) for url, _ in transport.calls] == ['/robots.txt', '/', '/okay']


def test_status_denial_does_not_retry_even_with_retry_after():
    report, transport, clock = collect({'/': response(status=429, **{'retry-after': '1'})})
    assert report.stop_reason == 'rate_limited'
    assert len(transport.calls) == 2
    assert clock.waits == [1.5]


def test_record_budget_stops_before_another_page_request():
    report, transport, _ = collect({'/': response('<p>Research</p><a href="/never">next</a>')}, max_records=1)
    assert report.stop_reason == 'record_limit'
    assert len(transport.calls) == 2


def test_frontier_truncation_is_visible_as_outcome():
    report, _, _ = collect({'/': response('<p>Research</p><a href="/never">next</a>')}, max_frontier=1)
    assert report.stop_reason == 'frontier_limit'


def test_robots_reserved_and_utf8_octets_match_consistently():
    robots = RobotsRules('User-agent: *\nDisallow: /private%3Adata\nDisallow: /தமிழ்\n'
        'Disallow: /literal%2A\nDisallow: /literal%24', 'SpiderDeckBot/0.1')
    assert not robots.allows(ORIGIN + '/private:data')
    assert not robots.allows(ORIGIN + '/private%3Adata')
    assert not robots.allows(normalize_url(ORIGIN + '/தமிழ்'))
    assert not robots.allows(ORIGIN + '/literal*')
    assert not robots.allows(ORIGIN + '/literal$')


def test_invalid_length_header_stops_without_transient_retry(sockets):
    pending, _ = sockets
    pending.append(wire(b'', b'Content-Length: ' + b'9' * 100 + b'\r\n'))
    with pytest.raises(CollectionError, match='invalid_content_length'):
        request()
