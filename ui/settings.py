"""Read-only summary and confirmed crawl settings edits; never opens SQLite."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.config import AppConfig
from core.config_store import approved_hosts
from ui.display import terminal_text


def as_json(config: AppConfig) -> str:
    # ASCII JSON escapes terminal controls and bidirectional formatting characters.
    return json.dumps(asdict(config), ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)


def show(config: AppConfig, config_path: Path, root: Path) -> None:
    print("Settings (read-only)")
    print("Config: " + terminal_text(str(config_path), 500))
    output = root / Path(config.output.dir).expanduser()
    print("Output: " + terminal_text(str(output), 500))
    print("Database: opens only when a data workflow needs it.")
    print("\nLocal imports")
    print(f"  File limit: {config.imports.max_file_bytes / 1024**2:g} MiB; records: {config.imports.max_records}")
    print("\nAuthorized web collection")
    print("  Exact hosts: " + terminal_text(", ".join(approved_hosts(config.crawl.allowed_domains)) or "(none configured)", 1000))
    print(f"  Pages: {config.crawl.max_pages}; depth: {config.crawl.max_depth}; delay: {config.crawl.delay_seconds:g}s")
    print(f"  Timeout: {config.crawl.timeout_seconds:g}s; transport attempts: {config.crawl.max_requests}")
    print("  Robots enforced; every run requires explicit target approval.")
    print("\nOffline ranking")
    print(f"  Weights: text={config.ranking.text_weight:g}, keyword={config.ranking.keyword_weight:g}, domain={config.ranking.domain_weight:g}")
    print(f"  Comparison limit: {config.ranking.max_records} records; top {config.ranking.top_k} per idea")
    print("\nThis summary is read-only. Interactive actions below require confirmation before saving.")


def run(config: AppConfig, config_path: Path, root: Path, *, dry_run: bool = False) -> None:
    from dataclasses import asdict, replace
    from core.config import CrawlConfig
    from core.config_store import ConfigEditor, ConfigWriteError, LIMIT_FIELDS, approved_hosts
    from security.network_policy import hostname, CollectionError
    from ui import menu

    show(config, config_path, root)
    while True:
        choice = menu.prompt_choice('Settings actions:', ['View approved hostnames', 'Add approved hostname',
            'Remove approved hostname', 'Configure crawl limits', 'Restore default crawl limits',
            'Reload saved crawl settings', 'Recover unreadable configuration', 'Back'])
        if not choice or choice == 'Back':
            return
        try:
            if choice == 'View approved hostnames':
                hosts = approved_hosts(config.crawl.allowed_domains)
                print('Approved exact hostnames: ' + (', '.join(hosts) or '(none)'))
                print('Legacy URL/invalid entries are inactive. Every collection run requires separate authorization.')
                continue
            if dry_run:
                print('Dry run: settings left untouched.')
                continue
            editor = ConfigEditor(config_path)
            if choice == 'Reload saved crawl settings':
                config.crawl = editor.current().crawl
                print('Saved crawl settings reloaded. Other settings require restarting.')
                continue
            if choice == 'Recover unreadable configuration':
                try:
                    editor.current()
                except ConfigWriteError:
                    if menu.confirm('Back up the unreadable file privately and replace configuration with documented defaults? No database will be changed.'):
                        config.crawl = editor.recover().crawl
                        print('Configuration recovered. The original is in a private .spiderdeck-config-backup-*.toml beside it. Restart before other workflows.')
                else:
                    print('Configuration is readable. Use the individual settings actions; no recovery was performed.')
                continue
            changes = {}
            if choice == 'Add approved hostname':
                raw = menu.prompt_text('Exact hostname only (e.g. research.example.org; blank cancels):')
                if not raw.strip():
                    continue
                host = hostname(raw.strip())
                if host in approved_hosts(config.crawl.allowed_domains):
                    print('This exact hostname is already approved.')
                    continue
                changes = {'allowed_domains': [*config.crawl.allowed_domains, host]}
                print('Approve exact hostname: ' + host + '. This does not approve subdomains or start collection.')
            elif choice == 'Remove approved hostname':
                entries = config.crawl.allowed_domains
                labels = []
                for index, value in enumerate(entries):
                    try:
                        label = hostname(value)
                    except CollectionError:
                        label = 'Inactive legacy entry'
                    labels.append(f'{index + 1}: {label}')
                selected = menu.prompt_choice('Remove which saved entry?', labels)
                if not selected:
                    continue
                index = labels.index(selected)
                changes = {'allowed_domains': [value for position, value in enumerate(entries) if position != index]}
            elif choice == 'Configure crawl limits':
                labels = [f'{key} = {getattr(config.crawl, key)}' for key in LIMIT_FIELDS]
                selected = menu.prompt_choice('Choose a limit (bytes for size limits, seconds for timing):', labels)
                if not selected:
                    continue
                key = selected.split(' = ', 1)[0]
                raw = menu.prompt_text('New value (blank cancels):')
                if not raw.strip():
                    continue
                value = float(raw) if key in {'delay_seconds', 'timeout_seconds', 'max_duration_seconds'} else int(raw)
                replace(config.crawl, **{key: value})  # Validate before asking to write.
                changes = {key: value}
                print(f'Proposed change: {key} = {value}')
            elif choice == 'Restore default crawl limits':
                defaults = asdict(CrawlConfig())
                changes = {key: defaults[key] for key in LIMIT_FIELDS}
                print(json.dumps(changes, sort_keys=True, indent=2))
                print('Approved hostnames and other settings will be preserved.')
            if changes and menu.confirm('Save these configuration changes atomically and keep a private backup?'):
                config.crawl = editor.save_crawl(changes, expected=config.crawl).crawl
                print('Settings saved. Current session crawl settings updated; unrelated TOML values were preserved.')
        except menu.PromptCancelled:
            print('Settings action cancelled; no incomplete edit saved.')
        except ConfigWriteError as exc:
            print(str(exc))
        except (ValueError, TypeError):
            print('Invalid setting. Use an exact public hostname or a finite, valid limit. No settings were written.')
