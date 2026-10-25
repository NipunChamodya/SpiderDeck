"""Real TLS over a loopback HTTPS server; routing substitution exists only here.

Production still rejects loopback and nonstandard ports. The socket adapter maps
one approved public test endpoint to the ephemeral local listener. OpenSSL, SNI,
certificate validation, HTTP parsing and cancellation remain real.
"""
from __future__ import annotations

import socket
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import crawler.fetcher as fetcher
from security.network_policy import CollectionError, NetworkPolicy, approve_target

HOST = 'research.test'
PUBLIC = '8.8.8.8'
URL = 'https://research.test/'


def issue(key, name, issuer, signing_key, *, ca=False, expired=False, dns=None):
    now = datetime.now(timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(issuer)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=10))
        .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=10))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signing_key.public_key()), critical=False))
    if dns:
        builder = (builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(dns)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False))
    return builder.sign(signing_key, hashes.SHA256())


@pytest.fixture(scope='module')
def certificates(tmp_path_factory):
    root = tmp_path_factory.mktemp('tls-certificates')
    result = {}
    for label in ('trusted', 'untrusted'):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label + ' test CA')])
        ca = issue(key, name, name, key, ca=True)
        path = root / (label + '-ca.pem')
        path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        path.chmod(0o600)
        result[label] = (key, name, path)
    for label, authority, expired, dns in (
            ('valid', 'trusted', False, HOST), ('expired', 'trusted', True, HOST),
            ('untrusted-leaf', 'untrusted', False, HOST),
            ('mismatch', 'trusted', False, 'different.test')):
        issuer_key, issuer, _ = result[authority]
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns)])
        leaf = issue(key, name, issuer, issuer_key, expired=expired, dns=dns)
        cert_path, key_path = root / (label + '.pem'), root / (label + '.key')
        cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cert_path.chmod(0o600)
        key_path.chmod(0o600)
        result[label] = cert_path, key_path
    return result


@contextmanager
def https_server(certificates, label='valid', *, stall=False, responses=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(*map(str, certificates[label]))
    names, requests, errors = [], [], []
    context.set_servername_callback(lambda sock, name, ctx: names.append(name))
    stop, accepted = threading.Event(), threading.Event()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(2)
    try:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
    except BaseException:
        listener.close()
        raise
    endpoint = listener.getsockname()
    def serve():
        try:
            for response_index in range(len(responses) if responses else 1):
                raw, _ = listener.accept()
                with raw:
                    raw.settimeout(2)
                    accepted.set()
                    if stall:
                        stop.wait(3)
                        return
                    with context.wrap_socket(raw, server_side=True) as secured:
                        data = b''
                        while b'\r\n\r\n' not in data and len(data) < 8192:
                            block = secured.recv(1024)
                            if not block:
                                break
                            data += block
                        requests.append(data)
                        body = b'<p>local TLS fixture</p>'
                        secured.sendall(responses[response_index] if responses else b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n'
                            b'Content-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
        except (OSError, ssl.SSLError) as exc:
            errors.append(type(exc))
    worker = threading.Thread(target=serve, name='spiderdeck-test-https')
    worker.start()
    try:
        yield SimpleNamespace(endpoint=endpoint, names=names, requests=requests,
                              errors=errors, accepted=accepted)
    finally:
        stop.set()
        listener.close()
        worker.join(4)
        assert not worker.is_alive(), 'HTTPS fixture leaked a server thread'


def local_route(monkeypatch, server, certificates):
    class RoutedSocket(socket.socket):
        def connect(self, endpoint):
            assert endpoint == (PUBLIC, 443)
            return super().connect(server.endpoint)
        def getpeername(self):
            super().getpeername()  # Require a genuinely connected descriptor.
            return PUBLIC, 443
    monkeypatch.setattr(fetcher, 'socket', SimpleNamespace(socket=RoutedSocket,
        AF_INET=socket.AF_INET, AF_INET6=socket.AF_INET6,
        SOCK_STREAM=socket.SOCK_STREAM, SHUT_RDWR=socket.SHUT_RDWR))
    def trust_test_ca(context, purpose=ssl.Purpose.SERVER_AUTH):
        assert purpose == ssl.Purpose.SERVER_AUTH
        context.load_verify_locations(cafile=str(certificates['trusted'][2]))
    monkeypatch.setattr(ssl.SSLContext, 'load_default_certs', trust_test_ca)
    policy = NetworkPolicy(approve_target(URL, [HOST], authorized=True), [HOST])
    monkeypatch.setattr(policy, 'resolve', lambda url: (policy.check_url(url), (PUBLIC,)))
    return policy


@pytest.mark.parametrize('label', ['valid', 'expired', 'untrusted-leaf', 'mismatch'])
def test_real_certificate_validation(certificates, monkeypatch, label, caplog, capsys):
    verification_codes = []
    original_handshake = ssl.SSLSocket.do_handshake
    def observed_handshake(sock, *args, **kwargs):
        try:
            return original_handshake(sock, *args, **kwargs)
        except ssl.SSLCertVerificationError as error:
            verification_codes.append(error.verify_code)
            raise
    monkeypatch.setattr(ssl.SSLSocket, 'do_handshake', observed_handshake)
    with https_server(certificates, label) as server:
        policy = local_route(monkeypatch, server, certificates)
        if label == 'valid':
            result = fetcher.PinnedTransport().request(URL, policy,
                user_agent='SpiderDeckBot/0.1', timeout=2, max_bytes=1024)
            assert result.status == 200
            assert result.body == b'<p>local TLS fixture</p>'
            assert server.requests[0].startswith(b'GET / HTTP/1.1\r\n')
        else:
            with pytest.raises(CollectionError, match='^tls_verification_failed$') as caught:
                fetcher.PinnedTransport().request(URL, policy,
                    user_agent='SpiderDeckBot/0.1', timeout=2, max_bytes=1024)
            assert caught.value.__cause__ is None
            codes = {'expired': 10, 'untrusted-leaf': 20, 'mismatch': 62}
            assert verification_codes == [codes[label]]
            assert not server.requests
        assert server.names == [HOST]  # SNI uses the approved name, never the pinned IP.
    assert not caplog.text
    assert capsys.readouterr() == ('', '')


def test_real_tls_handshake_timeout(certificates, monkeypatch):
    with https_server(certificates, stall=True) as server:
        policy = local_route(monkeypatch, server, certificates)
        with pytest.raises(CollectionError, match='^request_timeout$'):
            fetcher.PinnedTransport().request(URL, policy,
                user_agent='SpiderDeckBot/0.1', timeout=0.2, max_bytes=1024)
        assert server.accepted.is_set()
        assert not server.requests


def test_real_tls_handshake_cancellation(certificates, monkeypatch):
    with https_server(certificates, stall=True) as server:
        local_route(monkeypatch, server, certificates)
        connection = fetcher._PinnedConnection(HOST, 443, PUBLIC, timeout=3, tls=True)
        entering, outcomes = threading.Event(), []
        original = ssl.SSLSocket.do_handshake
        def handshake(sock, *args, **kwargs):
            assert connection.active_socket is sock
            entering.set()
            return original(sock, *args, **kwargs)
        monkeypatch.setattr(ssl.SSLSocket, 'do_handshake', handshake)
        def connect():
            try:
                connection.connect()
            except (OSError, CollectionError) as exc:
                outcomes.append(type(exc))
        worker = threading.Thread(target=connect, name='spiderdeck-test-tls-cancel')
        worker.start()
        try:
            assert entering.wait(2)
            assert server.accepted.wait(2)
            connection.abort()
            worker.join(1)
            assert not worker.is_alive(), 'cancellation left a TLS handshake running'
            assert outcomes
            assert connection.active_socket.fileno() == -1
        finally:
            connection.abort()
            worker.join(4)
            connection.close()
            assert not worker.is_alive()


def test_keyboard_interrupt_during_real_handshake_closes_socket(certificates, monkeypatch):
    import signal
    old_handler = signal.getsignal(signal.SIGALRM)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    wrapped = []
    original = ssl.SSLSocket.do_handshake
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    def handshake(sock, *args, **kwargs):
        wrapped.append(sock)
        signal.setitimer(signal.ITIMER_REAL, 0.05)
        return original(sock, *args, **kwargs)
    with https_server(certificates, stall=True) as server:
        policy = local_route(monkeypatch, server, certificates)
        monkeypatch.setattr(ssl.SSLSocket, 'do_handshake', handshake)
        signal.signal(signal.SIGALRM, interrupt)
        try:
            with pytest.raises(KeyboardInterrupt):
                fetcher.PinnedTransport().request(URL, policy,
                    user_agent='SpiderDeckBot/0.1', timeout=2, max_bytes=1024)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
        assert server.accepted.is_set()
        assert len(wrapped) == 1
        assert wrapped[0].fileno() == -1
        assert not server.requests


def test_real_https_preflight_reuses_seed_then_persists(certificates, monkeypatch, tmp_path):
    from core.config import CrawlConfig
    from core.storage import RecordStore
    from crawler.collector import Collector
    def reply(media, body):
        return (b'HTTP/1.1 200 OK\r\nContent-Type: ' + media + b'\r\nContent-Length: '
                + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
    responses = [reply(b'text/plain', b'User-agent: *\nAllow: /'),
                 reply(b'text/html', b'<p>Real TLS research fixture</p>')]
    with https_server(certificates, responses=responses) as server:
        local_route(monkeypatch, server, certificates)
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC, 443))])
        config = CrawlConfig(allowed_domains=[HOST], max_pages=1, delay_seconds=0.01)
        collector = Collector(approve_target(URL, [HOST], authorized=True), config)
        report = collector.preflight()
        assert collector.ready
        assert report.requests == 2
        assert len(report.documents) == 1
        assert not (tmp_path / 'output').exists()
        report = collector.run()
        assert report.stop_reason == 'completed'
        assert report.requests == 2
        store = RecordStore(tmp_path / 'output')
        assert store.save_import(report.documents[0]).inserted == 1
        assert store.count() == 1
        assert len(server.requests) == 2
        assert not server.errors


def test_real_https_conditional_get_reuses_verified_evidence(certificates,monkeypatch,tmp_path):
    from core.config import CrawlConfig
    from core.storage import RecordStore
    from crawler.collector import Collector
    from research.models import ResearchProject
    from research.relevance import ResearchProfile
    from research.storage import ProjectStore
    from research.cache import ResearchCache
    def reply(media,body,extra=b''):
        return (b'HTTP/1.1 200 OK\r\nContent-Type: '+media+b'\r\nContent-Length: '+str(len(body)).encode()
                +b'\r\n'+extra+b'Connection: close\r\n\r\n'+body)
    robots=reply(b'text/plain',b'User-agent: *\nAllow: /')
    page=reply(b'text/html',b'<h1>Phishing WebAssembly</h1><p>Phishing WebAssembly research</p>',b'ETag: "v1"\r\n')
    unchanged=b'HTTP/1.1 304 Not Modified\r\nConnection: close\r\n\r\n'
    with https_server(certificates,responses=[robots,page,robots,unchanged]) as server:
        local_route(monkeypatch,server,certificates)
        monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',(PUBLIC,443))])
        records=RecordStore(tmp_path/'output');api=ProjectStore(records)
        project=ResearchProject('Phishing WebAssembly',keywords=('phishing','WebAssembly'));api.create(project)
        cache=ResearchCache(records)
        config=CrawlConfig(allowed_domains=[HOST],max_pages=1,delay_seconds=.01)
        def collect():
            return Collector(approve_target(URL,[HOST],authorized=True),config,profile=ResearchProfile(project),cache=cache).run()
        first=collect();assert len(first.documents)==1
        api.ingest(project,first.documents[0]);cache.remember(first.documents[0],first.cache_validators[URL])
        second=collect();assert second.unchanged_pages==1
        assert api.ingest(project,second.documents[0]).duplicates==1
        assert records.count()==1
        assert b'If-None-Match: "v1"\r\n' in server.requests[-1]
        assert all(b'Cookie:' not in request and b'Authorization:' not in request for request in server.requests)
