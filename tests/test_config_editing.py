import fcntl
import os
import tomllib
from dataclasses import replace

import pytest

from core.config import CrawlConfig, load_config
from core.config_store import ConfigEditor, ConfigWriteError, approved_hosts, patch_crawl


def test_patch_preserves_comments_and_unrelated_sections():
    text = '# header\n[crawl] # targets\nallowed_domains = [\n "research.test", # entry\n]\nmax_pages = 5 # budget\n\n[output]\ndir = "private" # keep\n'
    updated = patch_crawl(text, {'max_pages': 8, 'allowed_domains': ['research.test', 'new.test']})
    assert 'max_pages = 8 # budget' in updated
    assert '[output]\ndir = "private" # keep' in updated
    assert '# header\n[crawl] # targets' in updated
    assert tomllib.loads(updated)['crawl']['allowed_domains'] == ['research.test', 'new.test']


def test_atomic_save_backups_and_snapshot_conflict(tmp_path):
    path = tmp_path / 'config.toml'
    original = '# preserve\n[crawl]\nmax_pages = 5\n[output]\ndir = "chosen"\n'
    path.write_text(original)
    first, stale = ConfigEditor(path), ConfigEditor(path)
    changed = first.save_crawl({'max_pages': 7}, expected=first.current().crawl)
    assert changed.crawl.max_pages == 7
    assert path.stat().st_mode & 0o777 == 0o600
    backups = list(tmp_path.glob('.spiderdeck-config-backup-*.toml'))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert backups[0].stat().st_mode & 0o777 == 0o600
    with pytest.raises(ConfigWriteError, match='changed'):
        stale.save_crawl({'max_pages': 9}, expected=stale.current().crawl)
    assert load_config(path).crawl.max_pages == 7
    assert not list(tmp_path.glob('*.tmp'))


def test_configuration_corruption_recovery_preserves_original(tmp_path):
    path = tmp_path / 'config.toml'
    original = b'PRIVATE_INVALID_TOML = [\xff'
    path.write_bytes(original)
    editor = ConfigEditor(path)
    with pytest.raises(ConfigWriteError, match='unreadable'):
        editor.current()
    config = editor.recover()
    assert config.crawl == CrawlConfig()
    assert load_config(path) == config
    assert next(tmp_path.glob('.spiderdeck-config-backup-*.toml')).read_bytes() == original


def test_invalid_changes_and_unrelated_settings_are_never_written(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\nmax_pages=5\n')
    editor = ConfigEditor(path)
    before = path.read_bytes()
    for change in ({'max_pages': -1}, {'allow_localhost': True}, {'respect_robots_txt': False},
                   {'allowed_domains': ['https://secret.test/path']}, {'allowed_domains': ['127.0.0.1']}):
        with pytest.raises(ValueError):
            editor.save_crawl(change, expected=editor.current().crawl)
        assert path.read_bytes() == before
    assert not list(tmp_path.glob('.spiderdeck-config-backup-*'))


def test_legacy_invalid_domains_stay_inactive_and_are_preserved(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\nallowed_domains=["https://example.test/private", "RESEARCH.test"]\n')
    editor = ConfigEditor(path)
    current = editor.current().crawl
    assert approved_hosts(current.allowed_domains) == ['research.test']
    config = editor.save_crawl({'allowed_domains': [*current.allowed_domains, 'new.test']}, expected=current)
    assert config.crawl.allowed_domains == [*current.allowed_domains, 'new.test']


def test_config_symlink_and_hardlink_refused(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\n')
    alias = tmp_path / 'linked.toml'
    alias.symlink_to(path)
    with pytest.raises(ConfigWriteError):
        ConfigEditor(alias)
    alias.unlink()
    os.link(path, alias)
    with pytest.raises(ConfigWriteError):
        ConfigEditor(path)


def test_concurrent_lock_refuses_write(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\n')
    editor = ConfigEditor(path)
    with path.open('rb') as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ConfigWriteError, match='Another process'):
            editor.save_crawl({'max_pages': 1}, expected=editor.current().crawl)
    assert path.read_text() == '[crawl]\n'


def test_complex_table_layout_refused_without_reformatting(tmp_path):
    path = tmp_path / 'config.toml'
    text = '["crawl"]\nmax_pages = 5\n'
    path.write_text(text)
    editor = ConfigEditor(path)
    with pytest.raises(ConfigWriteError):
        editor.save_crawl({'max_pages': 1}, expected=editor.current().crawl)
    assert path.read_text() == text


def test_failed_atomic_replace_keeps_original_and_backup(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\nmax_pages=3\n')
    original = path.read_bytes()
    editor = ConfigEditor(path)
    def fail(*args, **kwargs):
        raise OSError('PRIVATE filesystem detail')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(ConfigWriteError) as caught:
        editor.save_crawl({'max_pages': 5}, expected=editor.current().crawl)
    assert path.read_bytes() == original
    assert next(tmp_path.glob('.spiderdeck-config-backup-*')).read_bytes() == original
    assert not list(tmp_path.glob('*.tmp'))
    assert 'PRIVATE' not in str(caught.value)


def test_edit_during_backup_is_detected_before_replace(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    path.write_text('[crawl]\nmax_pages=3\n')
    editor = ConfigEditor(path)
    original_fsync = os.fsync
    calls = []
    newer = '[crawl]\nmax_pages=9\n'
    def fsync(fd):
        calls.append(fd)
        original_fsync(fd)
        if len(calls) == 2:  # Configuration temp and then backup.
            path.write_text(newer)
    monkeypatch.setattr(os, 'fsync', fsync)
    with pytest.raises(ConfigWriteError, match='changed'):
        editor.save_crawl({'max_pages': 5}, expected=editor.current().crawl)
    assert path.read_text() == newer
    assert not list(tmp_path.glob('*.tmp'))
