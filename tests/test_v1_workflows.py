"""Interactive V1 workflows with local fixtures and mocked desktop integration."""
from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.config import CrawlConfig, ImportConfig, load_config
from core.storage import RecordStore, SearchFilters
from crawler.collector import Collector
from security.network_policy import CollectionError, approve_target
from tests.test_collection import Clock, ScriptTransport, response
from ui import collection, importing, menu, native, records

URL = 'https://research.test/'


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))])
    routes = {'/robots.txt': response('User-agent: *\nAllow: /', media='text/plain'),
              '/': response('<p>Vision research</p><a href="/next">Next</a>'),
              '/next': response('<p>Sensor research</p>')}
    transport, clock = ScriptTransport(routes), Clock()
    made = []
    def factory(approval, config, **kwargs):
        result = Collector(approval, config, transport=transport, clock=clock,
                           sleep=clock.sleep, **kwargs)
        made.append(result)
        return result
    monkeypatch.setattr(collection, 'Collector', factory)
    monkeypatch.setattr(menu, 'prompt_url', lambda _: URL)
    def choose(message, choices):
        return 'Approve for this run only' if 'Approve this hostname' in message else 'Return to main menu'
    monkeypatch.setattr(menu, 'prompt_choice', choose)
    monkeypatch.setattr(native, 'open_browser', lambda url: pytest.fail('browser without opt-in'))
    return SimpleNamespace(transport=transport, clock=clock, routes=routes, made=made,
                           root=tmp_path / 'output')


def confirmations(monkeypatch, answers):
    values = iter(answers)
    monkeypatch.setattr(menu, 'confirm', lambda _: next(values))


def test_unapproved_target_cancellation_has_no_dns_http_storage(web, monkeypatch):
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: None)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: pytest.fail('DNS before approval'))
    collection.run(CrawlConfig(), lambda: pytest.fail('database before approval'), output_dir=web.root)
    assert not web.transport.calls
    assert not web.root.exists()


def test_run_only_approval_preflight_and_collection_reuse_seed(web, monkeypatch, capsys):
    config = CrawlConfig()
    confirmations(monkeypatch, [True, False, True])
    collection.run(config, lambda: RecordStore(web.root), output_dir=web.root)
    assert [call[0] for call in web.transport.calls] == [URL + 'robots.txt', URL, URL + 'next']
    assert RecordStore(web.root).count() == 2
    assert config.allowed_domains == []
    assert web.made[0].report.requests == 3
    assert web.made[0].report.links_discovered == 1
    audit = json.loads(next(web.root.glob('crawl-audit-*.json')).read_text())
    assert audit['records_saved'] == 2
    text = capsys.readouterr().out
    assert all(label in text for label in ['Checking target', 'Waiting for approval', 'Fetching page',
        'Extracting content', 'Saving records', 'Collection complete', 'Database:'])


def test_final_start_cancellation_saves_only_audit(web, monkeypatch):
    confirmations(monkeypatch, [True, False, False])
    collection.run(CrawlConfig(), lambda: pytest.fail('no database before start'), output_dir=web.root)
    assert len(web.transport.calls) == 2
    audit = json.loads(next(web.root.glob('crawl-audit-*.json')).read_text())
    assert audit['records_saved'] == 0
    assert audit['stop_reason'] == 'cancelled'
    assert not (web.root / 'spiderdeck.sqlite3').exists()


def test_save_hostname_requires_confirmation_and_still_needs_run_permission(web, monkeypatch, tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('# keep\n[output]\ndir="output"\n')
    config = load_config(path).crawl
    monkeypatch.setattr(menu, 'prompt_choice', lambda message, choices:
        'Save hostname for future use' if 'Approve this hostname' in message else 'Return to main menu')
    confirmations(monkeypatch, [True, True, False, True])
    collection.run(config, lambda: RecordStore(web.root), config_path=path, output_dir=web.root)
    assert load_config(path).crawl.allowed_domains == ['research.test']
    assert config.allowed_domains == ['research.test']
    assert '# keep' in path.read_text()
    assert len(list(tmp_path.glob('.spiderdeck-config-backup-*.toml'))) == 1
    confirmations(monkeypatch, [False])
    before = len(web.transport.calls)
    collection.run(config, lambda: pytest.fail('saved hostname does not grant run authorization'), output_dir=web.root)
    assert len(web.transport.calls) == before


def test_declined_persistence_makes_no_change_or_request(web, tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\n')
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: 'Save hostname for future use')
    confirmations(monkeypatch, [False])
    collection.run(CrawlConfig(), lambda: pytest.fail('no storage'), config_path=path, output_dir=web.root)
    assert path.read_text() == '[crawl]\n'
    assert not web.transport.calls


@pytest.mark.parametrize('url', ['not-a-url', 'file:///etc/passwd', 'https://user:PRIVATE@research.test/',
    'https://research.test/?token=PRIVATE', 'https://127.0.0.1/', 'https://research.test/%2e%2e/private'])
def test_invalid_urls_fail_before_approval(web, monkeypatch, url, capsys):
    monkeypatch.setattr(menu, 'prompt_url', lambda _: url)
    monkeypatch.setattr(menu, 'confirm', lambda *args: pytest.fail('invalid URL approval'))
    collection.run(CrawlConfig(), lambda: pytest.fail('storage'), output_dir=web.root)
    assert not web.transport.calls
    assert 'PRIVATE' not in capsys.readouterr().out


@pytest.mark.parametrize('restriction', ['dns', 'robots', 'redirect', 'authorization'])
def test_preflight_security_failure_never_starts_collection(web, monkeypatch, restriction, capsys):
    confirmations(monkeypatch, [True])
    if restriction == 'dns':
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    elif restriction == 'robots':
        web.routes['/robots.txt'] = response('User-agent: *\nDisallow: /', media='text/plain')
    elif restriction == 'redirect':
        web.routes['/'] = response(status=302, location='https://other.test/PRIVATE')
    else:
        web.routes['/'] = response(status=403)
    collection.run(CrawlConfig(), lambda: pytest.fail('storage after failed access check'), output_dir=web.root)
    assert not web.made[0].ready
    assert not (web.root / 'spiderdeck.sqlite3').exists()
    assert all('other.test' not in url for url, _ in web.transport.calls)
    text = capsys.readouterr().out
    assert 'Access check failed' in text
    assert 'PRIVATE' not in text


def test_browser_failure_does_not_block_approved_collection(web, monkeypatch, capsys):
    confirmations(monkeypatch, [True, True, True])
    monkeypatch.setattr(native, 'open_browser', lambda url: False)
    collection.run(CrawlConfig(), lambda: RecordStore(web.root), output_dir=web.root)
    assert RecordStore(web.root).count() == 2
    assert 'Browser could not be opened' in capsys.readouterr().out


def test_preflight_pause_does_not_fetch_links_and_preserves_total_budgets(web):
    config = CrawlConfig(allowed_domains=['research.test'], max_requests=2)
    crawler = Collector(approve_target(URL, config.allowed_domains, authorized=True), config,
        transport=web.transport, clock=web.clock, sleep=web.clock.sleep)
    assert len(crawler.preflight().documents) == 1
    assert crawler.ready
    assert len(web.transport.calls) == 2
    web.clock.now += 1000  # Thinking time cannot increase request or byte budgets.
    report = crawler.run()
    assert report.stop_reason == 'request_limit'
    assert len(web.transport.calls) == 2
    with pytest.raises(CollectionError, match='collector_already_used'):
        crawler.run()


def test_native_picker_success_preserves_unicode_spaces_and_avoids_shell(monkeypatch, tmp_path):
    path = tmp_path / 'නිපුන් தமிழ் notes.txt'
    path.write_text('vision')
    monkeypatch.setattr(native, 'desktop_available', lambda: True)
    def unavailable():
        raise native.DialogUnavailable
    monkeypatch.setattr(native, '_appkit_file', unavailable)
    monkeypatch.setattr(native, '_tk_file', unavailable)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=str(path) + '\n', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', run)
    assert native.select_document() == str(path)
    assert calls[0][0][:2] == ['/usr/bin/osascript', '-e']
    assert str(path) not in calls[0][0][-1]
    assert 'shell' not in calls[0][1]


def test_picker_cancellation_never_falls_back_or_imports(monkeypatch):
    monkeypatch.setattr(native, 'select_document', lambda: None)
    monkeypatch.setattr(menu, 'prompt_path', lambda _: pytest.fail('cancelled dialog is not unavailable'))
    importing.run(ImportConfig(), lambda: pytest.fail('storage after cancellation'))


def test_osascript_cancellation_and_browser_failure_are_sanitized(monkeypatch):
    monkeypatch.setattr(native.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(returncode=1, stdout='', stderr='PRIVATE User canceled. (-128)'))
    assert native._osascript_file() is None
    monkeypatch.setattr(native, 'sys', SimpleNamespace(platform='darwin'))
    assert not native.open_browser(URL)
    with pytest.raises(CollectionError):
        native.open_browser('https://user:PRIVATE@research.test/')


def test_headless_file_path_fallback(monkeypatch, tmp_path):
    path = tmp_path / 'notes.txt'
    path.write_text('research')
    def unavailable():
        raise native.DialogUnavailable
    monkeypatch.setattr(native, 'select_document', unavailable)
    monkeypatch.setattr(menu, 'prompt_path', lambda _: str(path))
    assert importing.choose_document() == str(path)


def test_import_preview_browse_search_and_export(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'නිපුන් Tamil notes.csv'
    path.write_text('Name,Expertise\nதமிழ்,vision\n')
    monkeypatch.setattr(native, 'select_document', lambda: str(path))
    actions = iter(['Browse imported records', 'Search imported content', 'Return to main menu'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: next(actions))
    monkeypatch.setattr(menu, 'prompt_text', lambda _: 'vision')
    store = RecordStore(tmp_path / 'output')
    importing.run(ImportConfig(), lambda: store)
    assert store.count(SearchFilters('vision', str(path), 'csv', exact_source=True)) == 1
    text = capsys.readouterr().out
    assert all(part in text for part in ['Filename:', 'file size:', 'Extracted characters:', 'Text preview', '1 matching records'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: 'imported.json')
    records.export(store, filters=SearchFilters(source=str(path), exact_source=True))
    assert json.loads((store.root / 'imported.json').read_text())[0]['fields']['Name'] == 'தமிழ்'


@pytest.mark.parametrize('name,data,config', [('bad.exe', b'hello', ImportConfig()),
    ('bad.pdf', b'%PDF-1.7\nPRIVATE_MALFORMED', ImportConfig()),
    ('large.txt', b'012345', ImportConfig(max_file_bytes=5))])
def test_import_error_is_actionable_without_storage(tmp_path, monkeypatch, capsys, name, data, config):
    path = tmp_path / name
    path.write_bytes(data)
    monkeypatch.setattr(native, 'select_document', lambda: str(path))
    importing.run(config, lambda: pytest.fail('no storage for invalid import'))
    output = capsys.readouterr().out
    assert 'Import failed' in output
    assert 'PRIVATE_MALFORMED' not in output


def test_password_pdf_message(tmp_path, monkeypatch, capsys):
    from pdfplumber.utils.exceptions import PdfminerException
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    path = tmp_path / 'password.pdf'
    path.write_bytes(b'%PDF-fixture')
    monkeypatch.setattr(native, 'select_document', lambda: str(path))
    with patch('pdfplumber.open', side_effect=PdfminerException(PDFPasswordIncorrect())):
        importing.run(ImportConfig(), lambda: pytest.fail('no unauthorized storage'))
    assert 'password-protected' in capsys.readouterr().out


def test_exact_source_filter_does_not_include_prefix_neighbours(tmp_path):
    from handlers.local import import_document
    source, other = tmp_path / 'notes.txt', tmp_path / 'notes.txt.copy.txt'
    source.write_text('vision')
    other.write_text('sensor')
    store = RecordStore(tmp_path / 'output')
    store.save_import(import_document(source))
    store.save_import(import_document(other))
    assert store.count(SearchFilters(source=str(source), exact_source=True)) == 1
    assert store.count(SearchFilters(source=str(source))) == 2


def test_existing_appkit_dialog_is_used_and_cancel_is_not_fallback(monkeypatch, tmp_path):
    import sys
    path = tmp_path / 'notes.txt'
    class Panel:
        def setTitle_(self, value): pass
        def setCanChooseFiles_(self, value): assert value
        def setCanChooseDirectories_(self, value): assert not value
        def setAllowsMultipleSelection_(self, value): assert not value
        def setAllowedFileTypes_(self, value): assert 'pdf' in value
        def runModal(self): return 1
        def URL(self): return SimpleNamespace(path=lambda: str(path))
    module = SimpleNamespace(NSModalResponseOK=1,
        NSApplication=SimpleNamespace(sharedApplication=lambda: SimpleNamespace(activateIgnoringOtherApps_=lambda value: None)),
        NSOpenPanel=SimpleNamespace(openPanel=lambda: Panel()))
    monkeypatch.setitem(sys.modules, 'AppKit', module)
    assert native._appkit_file() == str(path)
    monkeypatch.setattr(Panel, 'runModal', lambda self: 0)
    assert native._appkit_file() is None


def test_tk_dialog_cleanup_is_performed(monkeypatch, tmp_path):
    import sys
    states = []
    class Root:
        def withdraw(self): states.append('withdraw')
        def attributes(self, *args): pass
        def destroy(self): states.append('destroy')
    module = SimpleNamespace(Tk=Root, TclError=RuntimeError,
        filedialog=SimpleNamespace(askopenfilename=lambda **kwargs: str(tmp_path / 'notes.txt')))
    monkeypatch.setitem(sys.modules, 'tkinter', module)
    assert native._tk_file() == str(tmp_path / 'notes.txt')
    assert states == ['withdraw', 'destroy']


def test_import_preview_strips_terminal_controls(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'safe.txt'
    path.write_text('vision\x1b[31m\u202eTamil')
    monkeypatch.setattr(native, 'select_document', lambda: str(path))
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: None)
    importing.run(ImportConfig(), lambda: RecordStore(tmp_path / 'output'))
    output = capsys.readouterr().out
    assert '\x1b' not in output and '\u202e' not in output
    assert 'Text preview' in output


def test_import_another_document_does_not_retain_first_result(tmp_path, monkeypatch):
    paths = [tmp_path / 'one.txt', tmp_path / 'two.txt']
    for index, path in enumerate(paths): path.write_text(f'Research {index}')
    selected = iter(map(str, paths))
    monkeypatch.setattr(native, 'select_document', lambda: next(selected))
    actions = iter(['Import another document', 'Return to main menu'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: next(actions))
    store = RecordStore(tmp_path / 'output')
    importing.run(ImportConfig(), lambda: store)
    assert store.count() == 2


def test_failed_preflight_audit_reservation_makes_no_http(web, monkeypatch):
    confirmations(monkeypatch, [True])
    with patch('ui.collection.new_output_text', side_effect=PermissionError):
        with pytest.raises(PermissionError):
            collection.run(CrawlConfig(), lambda: pytest.fail('database'), output_dir=web.root)
    assert not web.transport.calls


def test_cancelled_start_prompt_records_no_data(web, monkeypatch):
    choices = iter([True, False])
    def confirm(_):
        try:
            return next(choices)
        except StopIteration:
            raise menu.PromptCancelled
    monkeypatch.setattr(menu, 'confirm', confirm)
    collection.run(CrawlConfig(), lambda: pytest.fail('no storage'), output_dir=web.root)
    assert len(web.transport.calls) == 2
    assert json.loads(next(web.root.glob('crawl-audit-*.json')).read_text())['stop_reason'] == 'cancelled'


def test_preflight_redirect_budget_is_tighter_than_collection_budget(web):
    config = CrawlConfig(allowed_domains=['research.test'], max_redirects=100, max_requests=200)
    for index in range(6):
        web.routes['/' if index == 0 else f'/step{index}'] = response(status=302, location=f'/step{index + 1}')
    collector = Collector(approve_target(URL, config.allowed_domains, authorized=True), config,
        transport=web.transport, clock=web.clock, sleep=web.clock.sleep)
    report = collector.preflight()
    assert not collector.ready
    assert report.stop_reason == 'redirect_limit'
    assert report.requests == 5  # robots + at most four responses in the seed chain.


def test_ui_normalizes_whitespace_case_path_and_fragment(web, monkeypatch):
    monkeypatch.setattr(menu, 'prompt_url', lambda _: '  HTTPS://RESEARCH.test/%7evision#section  ')
    web.routes['/~vision'] = response('<p>Vision</p>')
    confirmations(monkeypatch, [True, False, True])
    collection.run(CrawlConfig(), lambda: RecordStore(web.root), output_dir=web.root)
    assert web.transport.calls[1][0] == URL + '~vision'
    assert RecordStore(web.root).count() == 1


def test_web_results_export_and_collision_are_friendly(web, monkeypatch, capsys):
    follow = iter(['Export records', 'Export records', 'Return to main menu'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda message, choices:
        'Approve for this run only' if 'Approve this hostname' in message else next(follow))
    monkeypatch.setattr(menu, 'prompt_text', lambda _: 'web.json')
    confirmations(monkeypatch, [True, False, True])
    collection.run(CrawlConfig(), lambda: RecordStore(web.root), output_dir=web.root)
    assert len(json.loads((web.root / 'web.json').read_text())) == 2
    assert 'Export already exists' in capsys.readouterr().out


def test_database_failure_is_reflected_in_private_audit(web, monkeypatch):
    from core.storage import StorageError
    confirmations(monkeypatch, [True, False, True])
    def unavailable():
        raise StorageError('PRIVATE_INTERNAL_ERROR')
    collection.run(CrawlConfig(), unavailable, output_dir=web.root)
    text = next(web.root.glob('crawl-audit-*.json')).read_text()
    assert json.loads(text)['stop_reason'] == 'storage_failed'
    assert 'PRIVATE_INTERNAL_ERROR' not in text


def test_osascript_timeout_becomes_unavailable_without_diagnostics(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('PRIVATE', 300, stderr='PRIVATE')
    monkeypatch.setattr(native.subprocess, 'run', timeout)
    with pytest.raises(native.DialogUnavailable) as caught:
        native._osascript_file()
    assert 'PRIVATE' not in str(caught.value)
