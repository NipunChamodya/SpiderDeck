"""Confirmed settings edits, cancellation, defaults, and safe recovery."""
import argparse
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

import spiderdeck
from core.config import AppConfig, CrawlConfig, OutputConfig, load_config
from ui import menu, settings


def actions(monkeypatch, choices):
    values = iter(choices)
    monkeypatch.setattr(menu, 'prompt_choice', lambda *args: next(values))


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('# own comment\n[crawl]\nmax_pages=3\n[output]\ndir="custom-output"\n')
    return path


def test_add_remove_hostname_and_keep_unrelated_settings(saved, tmp_path, monkeypatch):
    config = load_config(saved)
    actions(monkeypatch, ['Add approved hostname', 'View approved hostnames',
                         'Remove approved hostname', '1: research.test', 'Back'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: 'research.test')
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    with patch('core.storage.RecordStore', side_effect=AssertionError('settings opened database')):
        settings.run(config, saved, tmp_path)
    assert config.crawl.allowed_domains == []
    assert load_config(saved).crawl.allowed_domains == []
    assert load_config(saved).output.dir == 'custom-output'
    assert '# own comment' in saved.read_text()
    assert len(list(tmp_path.glob('.spiderdeck-config-backup-*.toml'))) == 2
    assert not (tmp_path / 'custom-output').exists()


def test_declined_settings_save_and_cancel_leave_exact_bytes(saved, tmp_path, monkeypatch):
    config = load_config(saved)
    before = saved.read_bytes()
    actions(monkeypatch, ['Add approved hostname', 'Back'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: 'research.test')
    monkeypatch.setattr(menu, 'confirm', lambda _: False)
    settings.run(config, saved, tmp_path)
    assert saved.read_bytes() == before
    assert config.crawl.allowed_domains == []
    assert not list(tmp_path.glob('.spiderdeck-config-backup-*'))


@pytest.mark.parametrize('raw', ['https://research.test/path', 'localhost', '127.1', '*.example.test', 'user:PRIVATE@host.test'])
def test_settings_invalid_host_is_refused(saved, tmp_path, monkeypatch, raw, capsys):
    before = saved.read_bytes()
    actions(monkeypatch, ['Add approved hostname', 'Back'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: raw)
    monkeypatch.setattr(menu, 'confirm', lambda _: pytest.fail('invalid hostname confirmation'))
    settings.run(load_config(saved), saved, tmp_path)
    assert saved.read_bytes() == before
    assert 'PRIVATE' not in capsys.readouterr().out


def test_change_limits_restore_defaults_and_keep_hostname(saved, tmp_path, monkeypatch):
    config = load_config(saved)
    config.crawl.allowed_domains = ['research.test']
    saved.write_text(saved.read_text().replace('max_pages=3', 'max_pages=3\nallowed_domains=["research.test"]'))
    actions(monkeypatch, ['Configure crawl limits', 'max_pages = 3', 'Restore default crawl limits', 'Back'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: '7')
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    settings.run(config, saved, tmp_path)
    assert config.crawl.max_pages == CrawlConfig().max_pages
    assert load_config(saved).crawl.allowed_domains == ['research.test']
    assert load_config(saved).crawl.allow_localhost is False
    assert load_config(saved).crawl.respect_robots_txt is True


@pytest.mark.parametrize('raw', ['-1', 'nan', 'inf', '0'])
def test_invalid_limit_is_refused(saved, tmp_path, monkeypatch, raw):
    before = saved.read_bytes()
    actions(monkeypatch, ['Configure crawl limits', 'timeout_seconds = 10.0', 'Back'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: raw)
    monkeypatch.setattr(menu, 'confirm', lambda _: pytest.fail('invalid limit confirmation'))
    settings.run(load_config(saved), saved, tmp_path)
    assert saved.read_bytes() == before


def test_settings_stale_dialog_conflict_does_not_overwrite(saved, tmp_path, monkeypatch, capsys):
    config = load_config(saved)
    actions(monkeypatch, ['Add approved hostname', 'Back'])
    monkeypatch.setattr(menu, 'prompt_text', lambda _: 'research.test')
    newer = saved.read_text() + '\n# concurrent editor\n'
    def confirm(_):
        saved.write_text(newer)
        return True
    monkeypatch.setattr(menu, 'confirm', confirm)
    settings.run(config, saved, tmp_path)
    assert saved.read_text() == newer
    assert not config.crawl.allowed_domains
    assert 'changed' in capsys.readouterr().out


def test_recover_corrupt_configuration_from_settings(saved, tmp_path, monkeypatch):
    config = load_config(saved)
    corrupt = b'PRIVATE_CORRUPT_SOURCE = ['
    saved.write_bytes(corrupt)
    actions(monkeypatch, ['Recover unreadable configuration', 'Back'])
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    settings.run(config, saved, tmp_path)
    assert load_config(saved).crawl == CrawlConfig()
    assert next(tmp_path.glob('.spiderdeck-config-backup-*.toml')).read_bytes() == corrupt


def test_dry_run_settings_cannot_write(saved, tmp_path, monkeypatch):
    before = saved.read_bytes()
    actions(monkeypatch, ['Restore default crawl limits', 'Back'])
    settings.run(load_config(saved), saved, tmp_path, dry_run=True)
    assert saved.read_bytes() == before


def test_interactive_invalid_configuration_can_enter_safe_session(saved, monkeypatch):
    saved.write_text('PRIVATE_INVALID = [')
    before = saved.read_bytes()
    monkeypatch.setattr(spiderdeck.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(spiderdeck.sys.stdout, 'isatty', lambda: True)
    monkeypatch.setattr(menu, 'confirm', lambda _: True)
    seen = []
    monkeypatch.setattr(spiderdeck, '_run_menu', lambda args, config: seen.append(config))
    spiderdeck.run_menu(argparse.Namespace(config=str(saved), dry_run=False))
    assert seen[0].crawl.allowed_domains == []
    assert saved.read_bytes() == before


def test_settings_redacts_inactive_legacy_url(tmp_path, capsys):
    config = AppConfig(CrawlConfig(allowed_domains=['https://user:PRIVATE@host.test/?token=PRIVATE']), OutputConfig())
    settings.show(config, tmp_path / 'config.toml', tmp_path)
    assert 'PRIVATE' not in capsys.readouterr().out
