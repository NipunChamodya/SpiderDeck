"""Secrets may be imported as records, but must not enter diagnostics/audits."""
import io
import json
import logging
import traceback
import warnings

import pytest

from core.config import CrawlConfig
from core.logging_setup import get_logger, log_access
from crawler.collector import Collector, extract
from crawler.fetcher import Response
from handlers.local import DocumentImportError, import_document
from security.network_policy import CollectionError, approve_target, normalize_url
from tests.test_collection import Clock, ScriptTransport, response
from tests.test_local_import import pdf_bytes

SECRETS = ('Bearer PRIVATE_TOKEN_91', 'session=PRIVATE_COOKIE_92',
           'password=PRIVATE_PASSWORD_93', 'PRIVATE_DOCUMENT_94',
           'https://research.test/path?access_token=PRIVATE_QUERY_95')
PAYLOAD = ' '.join(SECRETS)


def assert_private(caplog, capsys):
    out, err = capsys.readouterr()
    combined = caplog.text + out + err
    for secret in SECRETS:
        assert secret not in combined


def test_real_pdf_debug_logs_are_private(tmp_path, caplog, capsys):
    path = tmp_path / 'private.pdf'
    path.write_bytes(pdf_bytes('PRIVATE_DOCUMENT_94'))
    with caplog.at_level(logging.DEBUG):
        result = import_document(path)
    assert 'PRIVATE_DOCUMENT_94' in result.records[0].text
    assert_private(caplog, capsys)


@pytest.mark.parametrize('web', [False, True])
def test_real_html_locator_warning_is_private(tmp_path, caplog, capsys, web):
    url = 'https://research.test/path?access_token=PRIVATE_QUERY_95'
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter('always')
        if web:
            result, _ = extract(Response('https://research.test/', 200,
                {'content-type': 'text/html'}, url.encode()), max_records=10, max_links=10)
        else:
            path = tmp_path / 'private.html'
            path.write_text(url)
            result = import_document(path)
    assert result.records
    assert not emitted
    assert any('diagnostics' in message.lower() for message in result.warnings)
    assert_private(caplog, capsys)


@pytest.mark.parametrize('failure', [ValueError, KeyboardInterrupt])
def test_parser_diagnostics_and_warning_hooks_restore_on_failure(tmp_path, monkeypatch, caplog, capsys, failure):
    from handlers import local
    path = tmp_path / 'private.txt'
    path.write_text(PAYLOAD)
    child = logging.getLogger('pdfminer.privacy_fixture')
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    child.addHandler(handler)
    old_handlers, old_propagate = list(child.handlers), child.propagate
    old_showwarning = warnings.showwarning
    def fail(*args):
        child.error(PAYLOAD)
        warnings.warn(PAYLOAD)
        if failure is KeyboardInterrupt:
            raise KeyboardInterrupt
        raise failure(PAYLOAD)
    monkeypatch.setattr(local, '_parse', fail)
    try:
        expected = KeyboardInterrupt if failure is KeyboardInterrupt else DocumentImportError
        with warnings.catch_warnings(record=True) as emitted, pytest.raises(expected) as caught:
            warnings.simplefilter('always')
            import_document(path)
        assert not emitted
        assert not stream.getvalue()
        assert str(caught.value) != PAYLOAD
        assert all(secret not in "".join(traceback.format_exception(caught.value)) for secret in SECRETS)
        assert child.handlers == old_handlers
        assert child.propagate == old_propagate
        assert warnings.showwarning is old_showwarning
        assert_private(caplog, capsys)
    finally:
        child.removeHandler(handler)
        handler.close()


def test_legacy_access_log_discards_raw_source_and_status(caplog, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = get_logger('spiderdeck.privacy_fixture')
    # Attach an explicit sink; the helper itself must not create a file.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        with caplog.at_level(logging.DEBUG):
            log_access(logger, PAYLOAD, PAYLOAD, items=3)
        assert all(secret not in stream.getvalue() for secret in SECRETS)
        assert 'items_collected=3' in stream.getvalue()
        assert not list(tmp_path.iterdir())
        assert_private(caplog, capsys)
    finally:
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.parametrize('suffix', ['?token=PRIVATE_QUERY_95', '/#PRIVATE_DOCUMENT_94'])
def test_rejected_url_errors_never_echo_input(suffix):
    url = 'https://user:PRIVATE_PASSWORD_93@research.test/' + suffix
    with pytest.raises(CollectionError) as caught:
        normalize_url(url)
    assert not any(secret in str(caught.value) for secret in ('PRIVATE_PASSWORD_93', 'PRIVATE_QUERY_95'))


def test_crawl_audit_omits_response_headers_documents_and_link_queries(caplog, capsys, monkeypatch):
    seed = 'https://research.test/'
    clock = Clock()
    from security.network_policy import NetworkPolicy
    monkeypatch.setattr(NetworkPolicy, 'resolve', lambda self, url: (self.check_url(url), ('8.8.8.8',)))
    transport = ScriptTransport({
        '/robots.txt': response('User-agent: *\nAllow: /', media='text/plain'),
        '/': response('<p>' + PAYLOAD + '</p><a href="?token=PRIVATE_QUERY_95">next</a>',
                      **{'set-cookie': SECRETS[1], 'authorization': SECRETS[0]}),
    })
    report = Collector(approve_target(seed, ['research.test'], authorized=True),
        CrawlConfig(allowed_domains=['research.test']), transport=transport,
        clock=clock, sleep=clock.sleep).run()
    assert report.documents
    audit = json.dumps(report.audit())
    assert all(secret not in audit for secret in SECRETS)
    assert not any(word in audit for word in ('set-cookie', 'authorization', '?token='))
    assert_private(caplog, capsys)


def test_arbitrary_adapter_error_never_becomes_audit_text():
    from crawler.collector import CrawlReport
    error = CollectionError(PAYLOAD)
    assert error.code == 'collection_failed'
    assert str(error) == 'collection_failed'
    report = CrawlReport('https://research.test')
    report.stop_reason = PAYLOAD
    report.event(PAYLOAD)
    assert all(secret not in json.dumps(report.audit()) for secret in SECRETS)
    assert report.audit()['stop_reason'] == 'collection_failed'


def test_diagnostic_context_restores_handlers_after_success(caplog):
    from security.parser_diagnostics import private_parser_diagnostics
    logger = logging.getLogger('pdfminer.privacy_restore')
    original_handlers = logger.handlers
    original_propagate = logger.propagate
    old_warning = warnings.showwarning
    with private_parser_diagnostics() as diagnostics:
        logger.warning(PAYLOAD)
        warnings.warn(PAYLOAD)
        logging.getLogger('spiderdeck.operational').warning('safe operational event')
    assert diagnostics.count == 2
    assert logger.handlers is original_handlers
    assert logger.propagate == original_propagate
    assert warnings.showwarning is old_warning
    assert 'safe operational event' in caplog.text
    assert all(secret not in caplog.text for secret in SECRETS)
    with caplog.at_level(logging.WARNING):
        logger.warning('safe restored event')
    assert 'safe restored event' in caplog.text


def test_selfcheck_current_policy_is_offline_and_makes_no_output(tmp_path, monkeypatch, capsys):
    import socket
    from security import selfcheck
    monkeypatch.chdir(tmp_path)
    def deny(*args, **kwargs):
        raise AssertionError('self-check attempted networking')
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    monkeypatch.setattr(socket, 'socket', deny)
    assert selfcheck.run(plain=True)
    output = capsys.readouterr().out
    assert sum(line.startswith('PASS |') for line in output.splitlines()) == 23
    assert not list(tmp_path.iterdir())


def test_selfcheck_detects_broken_live_ip_guard(monkeypatch, capsys):
    from security import selfcheck
    monkeypatch.setattr(selfcheck, 'public_ip', lambda value: value)
    assert not selfcheck.run(verbose=False, plain=True)
    assert 'SHOULD HAVE BLOCKED' in capsys.readouterr().out


def test_resolver_exception_traceback_is_sanitized(monkeypatch):
    import socket
    from security.network_policy import NetworkPolicy
    def fail(*args, **kwargs):
        raise OSError(PAYLOAD)
    monkeypatch.setattr(socket, 'getaddrinfo', fail)
    seed = 'https://research.test/'
    policy = NetworkPolicy(approve_target(seed, ['research.test'], authorized=True), ['research.test'])
    with pytest.raises(CollectionError, match='dns_resolution_failed') as caught:
        policy.resolve(seed)
    assert all(secret not in ''.join(traceback.format_exception(caught.value)) for secret in SECRETS)


def test_pdf_metadata_warning_is_private(tmp_path, monkeypatch, caplog, capsys):
    import pdfplumber.pdf
    original_document = pdfplumber.pdf.PDFDocument
    def document(*args, **kwargs):
        result = original_document(*args, **kwargs)
        result.info = [{'PRIVATE_METADATA_KEY': PAYLOAD}]
        return result
    def malformed_metadata(value):
        raise ValueError(PAYLOAD)
    monkeypatch.setattr(pdfplumber.pdf, 'PDFDocument', document)
    monkeypatch.setattr(pdfplumber.pdf, 'resolve_and_decode', malformed_metadata)
    path = tmp_path / 'metadata.pdf'
    path.write_bytes(pdf_bytes('Legitimate research text'))
    result = import_document(path)
    assert result.records
    assert any('diagnostics' in message.lower() for message in result.warnings)
    assert 'PRIVATE_METADATA_KEY' not in caplog.text
    assert_private(caplog, capsys)
