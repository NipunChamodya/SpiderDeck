"""Terminal behavior, cancellation safety, startup order and CLI exit codes."""
import argparse
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import spiderdeck
from core.config import AppConfig, CrawlConfig, OutputConfig, load_config
from core.storage import RecordStore
from rank.models import ResearchIdea
from ui import menu
from ui.display import DisplayOptions, options, use_options
from ui.progress import operation


def arguments(**kwargs):
    return argparse.Namespace(no_fx=False, dry_run=False, **kwargs)


def setup_menu(monkeypatch, tmp_path, security=True):
    monkeypatch.setenv('TERM', 'xterm-256color')
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.delenv('SPIDERDECK_REDUCED_MOTION', raising=False)
    monkeypatch.setattr('core.config.load_config', lambda: AppConfig(CrawlConfig(), OutputConfig(str(tmp_path / 'output'))))
    monkeypatch.setattr(menu, 'main_menu', lambda: '8) Quit')
    monkeypatch.setattr(spiderdeck, 'run_security_check', lambda: security)


def test_startup_is_static_by_default_and_checks_run_first(monkeypatch, tmp_path):
    from fx import effects
    setup_menu(monkeypatch, tmp_path)
    trace = []
    monkeypatch.setattr(spiderdeck, 'run_security_check', lambda: trace.append('security') or True)
    monkeypatch.setattr('ui.display.interactive_terminal', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **kw: trace.append('animation'))
    monkeypatch.setattr(effects, 'glitch_title', lambda *a, **kw: trace.append('title'))
    spiderdeck.run_menu(arguments())
    assert trace == ['security']
    spiderdeck.run_menu(arguments(animate=True))
    assert trace == ['security', 'security', 'animation', 'title']
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('kwargs', [{'quiet': True}, {'reduced_motion': True}, {'plain': True}])
def test_display_suppression_overrides_animation_opt_in(monkeypatch, tmp_path, kwargs):
    from fx import effects
    setup_menu(monkeypatch, tmp_path)
    monkeypatch.setattr('ui.display.interactive_terminal', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **kw: pytest.fail('motion should be disabled'))
    spiderdeck.run_menu(arguments(animate=True, **kwargs))


def test_no_fx_and_environment_reduced_motion(monkeypatch, tmp_path):
    from fx import effects
    setup_menu(monkeypatch, tmp_path)
    monkeypatch.setattr('ui.display.interactive_terminal', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **kw: pytest.fail('motion should be disabled'))
    spiderdeck.run_menu(argparse.Namespace(no_fx=True, dry_run=False, animate=True))
    monkeypatch.setenv('SPIDERDECK_REDUCED_MOTION', '1')
    spiderdeck.run_menu(arguments(animate=True))


def test_failed_security_check_disables_effects_and_retains_warning(monkeypatch, tmp_path, capsys):
    from fx import effects
    setup_menu(monkeypatch, tmp_path, security=False)
    monkeypatch.setattr('ui.display.interactive_terminal', lambda: True)
    monkeypatch.setattr(effects, 'matrix_intro', lambda **kw: pytest.fail('failed startup cannot animate'))
    spiderdeck.run_menu(arguments(animate=True, quiet=True))
    output = capsys.readouterr().out
    assert 'Security self-check failed' in output
    assert 'LOCAL RESEARCH INTELLIGENCE' not in output


def test_quiet_explicit_security_check_reports_actual_result(capsys):
    assert spiderdeck.main(['--security-check', '--quiet']) == 0
    assert capsys.readouterr().out == 'Security self-check: PASS\n'


def test_quiet_never_hides_failed_security_cases(monkeypatch, capsys):
    from security import selfcheck
    monkeypatch.setattr(selfcheck, '_case', lambda label, *a, **kw: (label, False, 'unexpected result'))
    assert spiderdeck.main(['--security-check', '--quiet']) == 1
    output = capsys.readouterr().out
    assert 'FAIL:' in output
    assert 'Security self-check: FAIL' in output


def test_display_preferences_are_scoped_after_error():
    before = options()
    with pytest.raises(RuntimeError):
        with use_options(DisplayOptions(quiet=True)):
            assert options().quiet
            raise RuntimeError
    assert options() == before


def test_show_settings_json_is_read_only_and_escapes_controls(tmp_path, capsys):
    config = tmp_path / 'chosen.toml'
    output = tmp_path / 'unused-output'
    config.write_text('[output]\ndir = ' + json.dumps(str(output)) + '\n[ranking]\ntext_weight=2\n')
    with patch('core.storage.RecordStore', side_effect=AssertionError('settings opened database')):
        assert spiderdeck.main(['--show-settings', '--config', str(config)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['output']['dir'] == str(output)
    assert data['ranking']['text_weight'] == 2
    assert not output.exists()
    from ui.settings import as_json
    cfg = AppConfig(CrawlConfig(), OutputConfig('folder\x1b[31m\u202e'))
    rendered = as_json(cfg)
    assert '\x1b' not in rendered and '\u202e' not in rendered
    assert json.loads(rendered)['output']['dir'] == cfg.output.dir


@pytest.mark.parametrize('body', ['SECRET_INVALID_TOML', 'fx=3', '[fx]\nenabled="false"',
    '[output]\ndir=3', 'ranking=[]', '[crawl]\nmax_pages=0'])
@pytest.mark.parametrize('show', [False, True])
def test_invalid_config_fails_clearly_without_source_leak(tmp_path, capsys, body, show):
    config = tmp_path / 'invalid.toml'
    config.write_text(body)
    args = ['--config', str(config)] + (['--show-settings'] if show else [])
    assert spiderdeck.main(args) == 2
    output = capsys.readouterr()
    assert 'Cannot load configuration' in output.err
    assert 'SECRET_INVALID' not in output.err
    assert 'Traceback' not in output.err


def test_missing_config_is_actionable(tmp_path, capsys):
    assert spiderdeck.main(['--config', str(tmp_path / 'missing.toml')]) == 2
    assert 'Cannot load configuration' in capsys.readouterr().err


def test_plain_main_menu_preserves_existing_numbers(monkeypatch):
    with use_options(DisplayOptions(plain=True)):
        monkeypatch.setattr('builtins.input', lambda _: '9')
        assert menu.main_menu().startswith('9) Export')
        monkeypatch.setattr('builtins.input', lambda _: '8')
        assert menu.main_menu().startswith('8) Quit')
        replies = iter(['invalid', 'q'])
        monkeypatch.setattr('builtins.input', lambda _: next(replies))
        assert menu.main_menu().startswith('8) Quit')


def test_plain_confirm_requires_explicit_yes(monkeypatch):
    with use_options(DisplayOptions(plain=True)):
        for text in ['', 'no', 'N']:
            monkeypatch.setattr('builtins.input', lambda _, text=text: text)
            assert menu.confirm('Approve target?') is False
        monkeypatch.setattr('builtins.input', lambda _: 'yes')
        assert menu.confirm('Approve target?') is True
        def closed(_):
            raise EOFError
        monkeypatch.setattr('builtins.input', closed)
        assert menu.confirm('Approve target?') is False


def test_plain_single_and_multiple_selection_validation(monkeypatch):
    with use_options(DisplayOptions(plain=True)):
        replies = iter(['bad', '4', '2'])
        monkeypatch.setattr('builtins.input', lambda _: next(replies))
        assert menu.prompt_choice('Choose', ['A', 'B']) == 'B'
        replies = iter(['bad', '3', '2,1,2'])
        monkeypatch.setattr('builtins.input', lambda _: next(replies))
        assert menu.prompt_multiple('Choose', ['A', 'B']) == ['A', 'B']


def test_interactive_questionary_navigation_is_preserved(monkeypatch):
    monkeypatch.setattr('ui.menu.interactive_terminal', lambda: True)
    answer = MagicMock()
    answer.ask.return_value = menu.MAIN_MENU_CHOICES[2]
    with patch('ui.menu.questionary.select', return_value=answer) as select:
        assert menu.main_menu() == menu.MAIN_MENU_CHOICES[2]
    assert select.call_args.kwargs['choices'] == menu.MAIN_MENU_CHOICES


@pytest.mark.parametrize('interrupt', [EOFError, KeyboardInterrupt])
def test_cancelled_text_is_not_an_intentional_blank(monkeypatch, interrupt):
    def cancel(_):
        raise interrupt
    with use_options(DisplayOptions(plain=True)):
        monkeypatch.setattr('builtins.input', cancel)
        with pytest.raises(menu.PromptCancelled):
            menu.prompt_text('Description:')
        assert menu.confirm('Approve?') is False
        assert menu.prompt_choice('Choose', ['A']) is None


def test_cancelled_idea_create_never_saves_partial_form(tmp_path, monkeypatch):
    from ui import ideas
    store = RecordStore(tmp_path / 'output')
    actions = iter(['Create idea', 'Back'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *a: next(actions))
    replies = iter(['New title'])
    def answer(_):
        try:
            return next(replies)
        except StopIteration:
            raise EOFError
    monkeypatch.setattr('builtins.input', answer)
    with use_options(DisplayOptions(plain=True)):
        ideas.run(store, AppConfig(CrawlConfig(), OutputConfig()).ranking)
    assert not store.list_ideas()


def test_cancelled_idea_edit_keeps_saved_contents(tmp_path, monkeypatch):
    from ui import ideas
    store = RecordStore(tmp_path / 'output')
    original = ResearchIdea('Original title', 'Original description')
    store.add_idea(original)
    actions = iter(['Edit idea', 'Back'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda message, choices:
                        choices[0] if message == 'Research idea:' else next(actions))
    replies = iter(['New title'])
    def answer(_):
        try:
            return next(replies)
        except StopIteration:
            raise EOFError
    monkeypatch.setattr('builtins.input', answer)
    with use_options(DisplayOptions(plain=True)):
        ideas.run(store, AppConfig(CrawlConfig(), OutputConfig()).ranking)
    assert store.list_ideas() == [original]


def test_progress_uses_no_refresh_thread_or_sleep(monkeypatch):
    from rich.console import Console
    monkeypatch.setattr('ui.progress.motion_enabled', lambda: True)
    with patch('rich.console.Console', return_value=Console(file=io.StringIO(), force_terminal=True)), \
         patch('threading.Thread.start', side_effect=AssertionError('background rendering thread')), \
         patch('time.sleep', side_effect=AssertionError('cosmetic sleep')):
        with operation('Export', total=3) as state:
            assert list(state.track([1, 2, 3])) == [1, 2, 3]
            assert state.completed == 3
    assert state._progress is None


def test_progress_display_failure_does_not_interrupt_work(monkeypatch):
    monkeypatch.setattr('ui.progress.motion_enabled', lambda: True)
    renderer = MagicMock()
    renderer.update.side_effect = OSError('display closed')
    with patch('rich.progress.Progress', return_value=renderer) as factory:
        with operation('Saving', total=3) as state:
            assert list(state.track([1, 2, 3])) == [1, 2, 3]
            assert state.completed == 3
    assert factory.call_args.kwargs['auto_refresh'] is False
    renderer.stop.assert_called_once()


def test_progress_quiet_has_no_status_output(capsys):
    with use_options(DisplayOptions(quiet=True)):
        with operation('PRIVATE_STATUS') as state:
            list(state.track([1, 2]))
    assert capsys.readouterr().out == ''


def test_operation_failure_is_not_swallowed(monkeypatch):
    with pytest.raises(ValueError, match='actual failure'):
        with operation('Saving'):
            raise ValueError('actual failure')


def test_keyboard_interrupt_exit_code_and_message(monkeypatch, capsys):
    monkeypatch.setattr(spiderdeck, 'run_menu', lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert spiderdeck.main(['--quiet']) == 130
    assert 'Previously committed records were preserved' in capsys.readouterr().out


def test_pipe_output_error_has_no_traceback(monkeypatch):
    monkeypatch.setattr(spiderdeck, 'run_menu', lambda _: (_ for _ in ()).throw(BrokenPipeError()))
    assert spiderdeck.main(['--quiet']) == 141


def test_real_piped_session_and_no_heavy_startup_imports(tmp_path):
    config = tmp_path / 'chosen.toml'
    output = tmp_path / 'unused-output'
    config.write_text('[output]\ndir=' + json.dumps(str(output)))
    code = ('import sys,spiderdeck; result=spiderdeck.main(sys.argv[1:]); '
            'assert not any(x in sys.modules for x in ("sklearn","numpy","torch","playwright","pdfplumber")); '
            'raise SystemExit(result)')
    result = subprocess.run([sys.executable, '-B', '-c', code, '--quiet', '--plain', '--config', str(config)],
                            input='8\n', capture_output=True, text=True, check=True)
    assert 'Goodbye.' in result.stdout
    assert '\x1b' not in result.stdout
    assert 'Input is not a terminal' not in result.stderr
    assert not output.exists()


def test_help_documents_modes_without_starting_application(capsys):
    with pytest.raises(SystemExit) as caught:
        spiderdeck.main(['--help'])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    for option in ['--quiet', '--no-animation', '--reduced-motion', '--plain', '--show-settings', '--config']:
        assert option in output


def audit_payload(**updates):
    data = {'origin': 'https://research.test', 'stop_reason': 'completed', 'pages_collected': 1,
            'records_collected': 2, 'records_saved': 2, 'requests': 2, 'events': [{'body': 'SECRET_BODY'}]}
    return {**data, **updates}


def write_audit(root, number, payload):
    path = root / f'crawl-audit-{number:032x}.json'
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    return path


def test_audit_summaries_read_only_and_do_not_expose_event_bodies(tmp_path, capsys):
    from ui.audit import show_summaries
    root = tmp_path / 'output'
    root.mkdir(mode=0o700)
    path = write_audit(root, 1, audit_payload())
    before = path.read_bytes()
    with patch('core.storage.RecordStore', side_effect=AssertionError('audit view opened database')):
        show_summaries(root)
    output = capsys.readouterr().out
    assert 'https://research.test | completed' in output
    assert 'records collected/saved: 2/2' in output
    assert 'SECRET_BODY' not in output
    assert path.read_bytes() == before
    assert not (root / 'spiderdeck.sqlite3').exists()


def test_audit_view_missing_output_does_not_create_it(tmp_path, capsys):
    from ui.audit import show_summaries
    root = tmp_path / 'missing'
    show_summaries(root)
    assert not root.exists()
    assert 'No collection audits' in capsys.readouterr().out


def test_audit_view_rejects_symlinks_hardlinks_and_untrusted_formats(tmp_path, capsys):
    from ui.audit import show_summaries
    root = tmp_path / 'output'
    root.mkdir(mode=0o700)
    outside = tmp_path / 'private.json'
    outside.write_text('SECRET_OUTSIDE')
    outside.chmod(0o600)
    (root / f'crawl-audit-{1:032x}.json').symlink_to(outside)
    os.link(outside, root / f'crawl-audit-{2:032x}.json')
    write_audit(root, 3, audit_payload(origin='https://user:SECRET@research.test/'))
    write_audit(root, 4, audit_payload(requests='SECRET_COUNT'))
    big = root / f'crawl-audit-{5:032x}.json'
    big.write_bytes(b'SECRET' * 12000)
    big.chmod(0o600)
    show_summaries(root)
    output = capsys.readouterr().out
    assert 'SECRET' not in output
    assert 'could not be read safely' in output
    assert outside.read_text() == 'SECRET_OUTSIDE'


def test_audit_view_limits_history_to_newest_twenty(tmp_path, capsys):
    from ui.audit import show_summaries
    root = tmp_path / 'output'
    root.mkdir(mode=0o700)
    for index in range(25):
        path = write_audit(root, index, audit_payload())
        os.utime(path, ns=(1_000_000 + index, 1_000_000 + index))
    show_summaries(root)
    output = capsys.readouterr().out
    assert output.count('https://research.test | completed') == 20
    assert f'crawl-audit-{0:032x}.json' not in output
    assert f'crawl-audit-{24:032x}.json' in output


def test_settings_menu_does_not_initialize_storage(monkeypatch, tmp_path, capsys):
    setup_menu(monkeypatch, tmp_path)
    choices = iter(['7) Settings', '8) Quit'])
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: 'Back')
    monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
    spiderdeck.run_menu(arguments())
    assert 'Settings (read-only)' in capsys.readouterr().out
    assert not (tmp_path / 'output').exists()


def test_quiet_security_menu_still_runs_checks(monkeypatch, tmp_path, capsys):
    setup_menu(monkeypatch, tmp_path)
    choices = iter(['6) Security', '8) Quit'])
    actions = iter(['Run offline security self-check', 'Back'])
    monkeypatch.setattr(menu, 'main_menu', lambda: next(choices))
    monkeypatch.setattr(menu, 'prompt_choice', lambda *a: next(actions))
    with patch('security.selfcheck.run', return_value=True) as check:
        spiderdeck.run_menu(arguments(quiet=True))
    check.assert_called_once()
    assert 'Security self-check: PASS' in capsys.readouterr().out
    assert not (tmp_path / 'output').exists()


def test_collection_continues_when_progress_renderer_fails(monkeypatch):
    import socket
    from crawler.collector import Collector
    from security.network_policy import approve_target
    from tests.test_collection import Clock, ScriptTransport, response, PUBLIC, ORIGIN
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC, 443))])
    monkeypatch.setattr('ui.progress.motion_enabled', lambda: True)
    renderer = MagicMock()
    renderer.update.side_effect = OSError('broken terminal')
    transport = ScriptTransport({'/robots.txt': response('', status=404), '/': response('<p>vision</p>')})
    clock = Clock()
    cfg = CrawlConfig(allowed_domains=['research.test'])
    with patch('rich.progress.Progress', return_value=renderer):
        with operation('Collecting') as state:
            result = Collector(approve_target(ORIGIN, cfg.allowed_domains, authorized=True), cfg,
                transport=transport, clock=clock, sleep=clock.sleep, on_progress=state.set_completed).run()
    assert result.stop_reason == 'completed'
    assert len(result.documents) == 1
    assert len(transport.calls) == 2


def test_real_piped_import_search_export_and_settings(tmp_path):
    config = tmp_path / 'config.toml'
    root = tmp_path / 'output'
    config.write_text('[output]\ndir=' + json.dumps(str(root)))
    source = tmp_path / 'people.csv'
    source.write_text('Name,Expertise\nA,computer vision\n')
    answers = ['2', str(source), '4', '3', '4', 'vision', '', 'csv', '9', '', '', '', 'records.json',
               '7', '8', '6', '2', '3', '8']
    result = subprocess.run([sys.executable, '-B', str(Path(spiderdeck.__file__)), '--plain', '--quiet',
                             '--config', str(config)], input='\n'.join(answers) + '\n',
                            capture_output=True, text=True, check=True)
    assert 'Imported 1 records' in result.stdout
    assert 'Exported 1 records' in result.stdout
    assert 'Settings (read-only)' in result.stdout
    assert 'Extracting local document' not in result.stdout
    assert '\x1b' not in result.stdout
    exported = json.loads((root / 'records.json').read_text())
    assert exported[0]['fields']['Name'] == 'A'
    assert RecordStore(root).count() == 1


def test_eof_at_web_approval_never_means_yes(tmp_path):
    root = tmp_path / 'output'
    config = tmp_path / 'config.toml'
    config.write_text('[output]\ndir=' + json.dumps(str(root)) + '\n[crawl]\nallowed_domains=["research.test"]')
    code = ('import ssl,socket,sys,spiderdeck; '
            'socket.socket=lambda *a,**kw: (_ for _ in ()).throw(AssertionError("network before consent")); '
            'raise SystemExit(spiderdeck.main(sys.argv[1:]))')
    result = subprocess.run([sys.executable, '-B', '-c', code, '--quiet', '--plain', '--config', str(config)],
        input='1\nhttps://research.test/\n', capture_output=True, text=True, check=True)
    assert 'Target not approved; no requests made' in result.stdout
    assert not root.exists()


def test_unknown_stage_totals_are_not_rendered_as_fake_percentages(monkeypatch):
    from rich.console import Console
    stream = io.StringIO()
    monkeypatch.setattr('ui.progress.motion_enabled', lambda: True)
    with patch('rich.console.Console', return_value=Console(file=stream, force_terminal=True)):
        with operation('Extracting local document'):
            pass
    output = stream.getvalue()
    assert 'Extracting local document' in output
    assert '0 processed' not in output
    assert '%' not in output


def test_plain_mode_environment_flags(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '')
    assert spiderdeck._display_options(arguments()).plain
    monkeypatch.delenv('NO_COLOR')
    monkeypatch.setenv('TERM', 'dumb')
    assert spiderdeck._display_options(arguments()).plain


def test_conflicting_animation_flags_fail_before_startup(capsys):
    with pytest.raises(SystemExit) as caught:
        spiderdeck.main(['--animate', '--no-animation'])
    assert caught.value.code == 2
    assert 'not allowed with argument' in capsys.readouterr().err
