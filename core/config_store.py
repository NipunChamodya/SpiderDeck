"""Explicit, backed-up, atomic edits to the selected TOML configuration.

Only crawl fields are edited. Unrelated bytes/comments remain untouched; unusual
TOML layouts are refused unless the parsed before/after values prove the edit.
Advisory locking coordinates SpiderDeck writers; snapshots detect stale dialogs.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import stat
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from core.config import AppConfig, CrawlConfig, OutputConfig, config_from_mapping
from security.filesystem import open_output_directory, verify_directory
from security.network_policy import hostname

MAX_CONFIG_BYTES = 256 * 1024
LIMIT_FIELDS = ('max_pages', 'max_depth', 'delay_seconds', 'timeout_seconds',
                'max_retries', 'max_redirects', 'max_requests', 'max_frontier',
                'max_response_bytes', 'max_total_bytes', 'max_records', 'max_duration_seconds')


class ConfigWriteError(ValueError):
    """A non-sensitive persistence or conflict message suitable for the UI."""


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    identity: tuple[int, int, int, int]


def approved_hosts(values: list[str]) -> list[str]:
    """Invalid legacy entries stay on disk but never grant approval."""
    result = []
    for value in values:
        try:
            checked = hostname(value)
        except ValueError:
            continue
        if checked not in result:
            result.append(checked)
    return result


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns


def _read(fd: int) -> Snapshot:
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
            or before.st_nlink != 1 or before.st_mode & 0o022 or before.st_size > MAX_CONFIG_BYTES):
        raise ConfigWriteError('Settings must be a small, owned regular file without hardlinks.')
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, MAX_CONFIG_BYTES + 1)
    after = os.fstat(fd)
    if len(data) > MAX_CONFIG_BYTES or len(data) != before.st_size or _identity(before) != _identity(after):
        raise ConfigWriteError('Configuration changed while reading. Reload settings and retry.')
    return Snapshot(data, _identity(after))


def _value_end(text: str, start: int) -> int:
    """Find a simple TOML value's end, respecting array strings and comments."""
    index, depth, quote = start, 0, ''
    while index < len(text):
        char = text[index]
        if quote:
            if text.startswith(quote, index):
                index += len(quote)
                quote = ''
                continue
            if char == '\\' and quote.startswith('"'):
                index += 2
                continue
        elif char in "\"'":
            quote = char * 3 if text.startswith(char * 3, index) else char
            index += len(quote)
            continue
        elif char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
        elif char == '#':
            if depth == 0:
                return index
            newline = text.find('\n', index)
            index = len(text) if newline < 0 else newline
            continue
        elif char in '\r\n' and depth == 0:
            return index
        index += 1
    return index


def patch_crawl(text: str, changes: dict) -> str:
    original = tomllib.loads(text)
    expected = copy.deepcopy(original)
    expected.setdefault('crawl', {}).update(changes)
    config_from_mapping(expected)
    # Canonical plain [crawl] is the repository's format. Parsed equality below
    # prevents matches inside strings or unusual layouts from corrupting data.
    headers = list(re.finditer(r'(?m)^[ \t]*\[crawl\][ \t]*(?:#[^\r\n]*)?\r?$', text))
    if len(headers) > 1:
        raise ConfigWriteError('Unsupported settings layout. No configuration was changed.')
    if not headers:
        if 'crawl' in original:
            raise ConfigWriteError('This TOML table layout cannot be edited safely. Use run-only approval.')
        text = text.rstrip() + '\n\n[crawl]\n'
        start, end = len(text), len(text)
    else:
        start = headers[0].end()
        following = re.search(r'(?m)^[ \t]*\[\[?[^\r\n]+\]\]?[ \t]*(?:#[^\r\n]*)?\r?$', text[start:])
        end = start + following.start() if following else len(text)
    section = text[start:end]
    for key, value in changes.items():
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
        matches = list(re.finditer(r'(?m)^([ \t]*' + re.escape(key) + r'[ \t]*=[ \t]*)', section))
        if len(matches) > 1:
            raise ConfigWriteError('Ambiguous settings layout. No configuration was changed.')
        if matches:
            match = matches[0]
            finish = _value_end(section, match.end())
            old = section[match.end():finish]
            trailing = old[len(old.rstrip()):]
            section = section[:match.end()] + encoded + trailing + section[finish:]
        else:
            section = section.rstrip() + '\n' + key + ' = ' + encoded + '\n\n'
    result = text[:start] + section + text[end:]
    if tomllib.loads(result) != expected:
        raise ConfigWriteError('This TOML layout cannot be edited without changing other settings.')
    return result


class ConfigEditor:
    def __init__(self, path: Path):
        self.path = path.expanduser().absolute()
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                self.snapshot = _read(fd)
            finally:
                os.close(fd)
        except OSError:
            raise ConfigWriteError('Cannot safely open settings. Check permissions; symlink settings are read-only.') from None

    def current(self) -> AppConfig:
        try:
            return config_from_mapping(tomllib.loads(self.snapshot.data.decode('utf-8')))
        except (ValueError, TypeError, UnicodeError):
            raise ConfigWriteError('Configuration is unreadable. Use the backed-up recovery action in Settings.') from None

    def save_crawl(self, changes: dict, *, expected: CrawlConfig) -> AppConfig:
        if not changes or any(key not in (*LIMIT_FIELDS, 'allowed_domains') for key in changes):
            raise ConfigWriteError('Only approved hostnames and documented crawl limits can be changed here.')
        if self.current().crawl != expected:
            raise ConfigWriteError('Saved crawl settings differ from this session. Reload crawl settings before saving.')
        if 'allowed_domains' in changes:
            values = changes['allowed_domains']
            old = self.current().crawl.allowed_domains
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ConfigWriteError('Approved hostnames must be a list of valid hostname strings.')
            # Existing invalid legacy entries may be retained, never newly added.
            for value in values:
                if value not in old:
                    hostname(value)
        try:
            text = patch_crawl(self.snapshot.data.decode('utf-8'), changes)
        except (UnicodeError, ValueError, TypeError):
            raise ConfigWriteError('Cannot safely edit this TOML layout. No settings were written; use run-only approval.') from None
        return self._publish(text)

    def recover(self) -> AppConfig:
        defaults = AppConfig(CrawlConfig(), OutputConfig())
        values = {'crawl': asdict(defaults.crawl), 'output': asdict(defaults.output),
                  'import': asdict(defaults.imports), 'ranking': {**asdict(defaults.ranking), 'offline_only': True},
                  'fx': {'enabled': True}}
        text = '\n'.join('[' + section + ']\n' + '\n'.join(
            key + ' = ' + json.dumps(value, ensure_ascii=True, allow_nan=False)
            for key, value in fields.items()) + '\n' for section, fields in values.items())
        return self._publish(text)

    def _check_snapshot(self, parent: int, fd: int) -> None:
        verify_directory(self.path.parent, parent)
        current = os.stat(self.path.name, dir_fd=parent, follow_symlinks=False)
        if _identity(current) != self.snapshot.identity or _read(fd) != self.snapshot:
            raise ConfigWriteError('Configuration changed before saving. Reload and review it again; no replacement was made.')

    def _publish(self, text: str) -> AppConfig:
        try:
            candidate = config_from_mapping(tomllib.loads(text))
            data = text.encode('utf-8')
            if len(data) > MAX_CONFIG_BYTES:
                raise ConfigWriteError('Configuration exceeds the safe edit size limit.')
            with open_output_directory(self.path.parent) as parent:
                fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                temporary = '.spiderdeck-config-' + uuid4().hex + '.tmp'
                created = False
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise ConfigWriteError('Another process is editing configuration. Retry after it finishes.') from None
                    if _read(fd) != self.snapshot:
                        raise ConfigWriteError('Configuration changed since this dialog opened. Reload and review it again.')
                    pending = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    created = True
                    with os.fdopen(pending, 'wb') as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    self._check_snapshot(parent, fd)
                    backup_name = '.spiderdeck-config-backup-' + uuid4().hex + '.toml'
                    backup = os.open(backup_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    with os.fdopen(backup, 'wb') as handle:
                        handle.write(self.snapshot.data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    self._check_snapshot(parent, fd)
                    os.replace(temporary, self.path.name, src_dir_fd=parent, dst_dir_fd=parent)
                    created = False
                    os.fsync(parent)
                finally:
                    if created:
                        os.unlink(temporary, dir_fd=parent)
                    os.close(fd)
            # Reopen the new inode so subsequent edits carry a fresh snapshot.
            self.snapshot = ConfigEditor(self.path).snapshot
            return candidate
        except ConfigWriteError:
            raise
        except (OSError, ValueError, TypeError):
            raise ConfigWriteError('Cannot save settings safely. Check ownership, permissions and disk space; inspect the saved file before retrying.') from None
