"""Interactive hostname approval, bounded audited preflight, then collection."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Callable
from uuid import uuid4
from urllib.parse import urlsplit

from core.config import CrawlConfig
from core.config_store import ConfigEditor, ConfigWriteError, approved_hosts
from core.storage import RecordStore, StorageError
from crawler.collector import Collector
from security.filesystem import new_output_text, output_directory
from security.network_policy import CollectionError, approve_target, hostname, normalize_url, origin
from ui import menu, native, records
from ui.display import notice, terminal_text
from ui.messages import collection_message
from ui.progress import operation


def _stage_notice(label: str) -> None:
    try:
        notice(label)
    except (OSError, UnicodeError):
        pass  # Cosmetic stage output cannot relax policy or interrupt processing.


def _follow_up(store: RecordStore, scope: str) -> None:
    from core.storage import SearchFilters
    while True:
        choice = menu.prompt_choice('Use the collected results (including previous runs on this origin):',
            ['Browse records', 'Search records', 'Export records', 'Return to main menu'])
        if not choice or choice == 'Return to main menu':
            return
        filters = SearchFilters(source=scope + '/')
        try:
            if choice == 'Export records':
                records.export(store, filters=filters)
            else:
                records.browse(store, search=choice == 'Search records', filters=filters)
        except FileExistsError:
            print('Export already exists. Choose a new filename; existing data was preserved.')
        except menu.PromptCancelled:
            print('Result action cancelled. Collected records remain saved.')
        except (StorageError, OSError, ValueError):
            print('Result action failed. Check filters, the export filename, output permissions and disk space; existing records remain saved.')


def run(config: CrawlConfig, get_store: Callable[[], RecordStore], *,
        config_path: Path | None = None, output_dir: Path | None = None) -> None:
    collector = None
    try:
        requested = menu.prompt_url('Complete public website URL (https://...; blank cancels):')
        if not requested.strip():
            return
        notice('Checking target')
        url = normalize_url(requested.strip())
        host = urlsplit(url).hostname
        scope = origin(url)
        hosts = approved_hosts(config.allowed_domains)
        invalid = 0
        for value in config.allowed_domains:
            try:
                hostname(value)
            except CollectionError:
                invalid += 1
        if invalid:
            print('Some saved hostname entries are invalid and inactive. Review them in Settings; entering a URL never approves it.')
        print('Hostname: ' + terminal_text(host))
        print('Page URL: ' + terminal_text(url, 4096))
        print(f'Requested scope: {scope}; up to {config.max_pages} pages; depth {config.max_depth}; delay {config.delay_seconds:g}s.')
        print('Static HTML/public JSON only. No browser login, cookies, CAPTCHA or access-control bypass.')
        print('Access checks pending: DNS/public IP, HTTPS certificate, robots and seed-page restrictions.')
        notice('Waiting for approval')
        run_config = replace(config, allowed_domains=hosts)
        if host not in hosts:
            print('This website has not been approved for collection. Review this exact hostname.')
            choice = menu.prompt_choice('Approve this hostname and bounded access checks?',
                ['Approve for this run only', 'Save hostname for future use', 'Cancel'])
            if choice not in {'Approve for this run only', 'Save hostname for future use'}:
                print('Target not approved; no requests made.')
                return
            if choice == 'Save hostname for future use':
                if config_path is None:
                    print('Saved settings are unavailable here. Choose run-only approval from the main menu.')
                    return
                if not menu.confirm('Save this exact hostname in configuration, keeping a private backup? This does not start collection.'):
                    return
                editor = ConfigEditor(config_path)
                updated = editor.save_crawl({'allowed_domains': [*config.allowed_domains, host]}, expected=config)
                config.allowed_domains = updated.crawl.allowed_domains
                print('Hostname saved. Every run still needs separate authorization.')
            run_config = replace(config, allowed_domains=[*hosts, host])
        if not menu.confirm(f'I have permission for automated access checks on {scope}: robots.txt and one seed page, with bounded same-origin redirects. Proceed?'):
            print('Target not approved; no requests made.')
            return
        if urlsplit(url).scheme == 'http' and not menu.confirm('HTTP has no transport encryption. Approve this HTTP origin for this run?'):
            return
        approval = approve_target(url, run_config.allowed_domains, authorized=True)
        # Preserve audit-before-network without initializing SQLite during checks.
        root = output_directory(output_dir) if output_dir is not None else get_store().root
        audit_name = f'crawl-audit-{uuid4().hex}.json'
        saved = duplicates = 0
        store = None
        with new_output_text(root, audit_name) as audit_file:
            collector = Collector(approval, run_config, on_stage=_stage_notice)
            try:
                with operation('Checking access permissions'):
                    report = collector.preflight()
                if collector.ready:
                    print('Access checks passed for the seed: public destination, transport policy, robots and supported static content.')
                    if urlsplit(url).scheme == 'https':
                        print('HTTPS certificate verification passed for fetched responses.')
                    print('This technical check does not establish permission to extract data.')
                    if menu.confirm('Open this approved URL in the default browser? Browser sessions remain separate from collection.'):
                        if not native.open_browser(url):
                            print('Browser could not be opened. You can continue collection independently.')
                    notice('Waiting for approval')
                    if menu.confirm(f'Start collection on {scope} with the displayed scope and limits? I have permission for this automated collection.'):
                        with operation('Collecting approved pages', unit='pages') as progress:
                            progress.set_completed(len(report.documents))
                            collector.on_progress = progress.set_completed
                            report = collector.run()
                        try:
                            with operation('Saving records'):
                                store = get_store()
                                for document in report.documents:
                                    summary = store.save_import(document)
                                    saved += summary.inserted
                                    duplicates += summary.duplicates
                        except (StorageError, OSError):
                            report.stop_reason = 'storage_failed'
                            report.event('storage_failed')
                    else:
                        collector.cancel()
                        print('Collection not started. No records saved from the access check.')
                else:
                    print('Access check failed. ' + collection_message(report.stop_reason))
            except (menu.PromptCancelled, KeyboardInterrupt):
                collector.cancel()
                print('Collection cancelled; previously committed records were preserved.')
            finally:
                if collector.ready:
                    collector.cancel()
                payload = collector.report.audit()
                payload.update(records_saved=saved, duplicate_identifiers=duplicates)
                json.dump(payload, audit_file, ensure_ascii=False, sort_keys=True, indent=2)
                audit_file.write('\n')
        report = collector.report
        print(collection_message(report.stop_reason))
        print(f'Pages collected: {len(report.documents)}; records extracted: {sum(len(doc.records) for doc in report.documents)}; '
              f'links discovered (bounded): {report.links_discovered}.')
        stops = int(report.stop_reason not in {'completed', 'cancelled', 'page_limit', 'frontier_limit'})
        print(f'Records saved: {saved}; duplicate identifiers: {duplicates}; errors/stops: {stops}; '
              f'skipped pages: {report.skipped_pages}; links not scheduled: {report.skipped_links}.')
        print(f'Audit saved as {audit_name} under output. Earlier accepted pages can survive a later restriction.')
        if store is not None:
            print('Database: ' + terminal_text(str(store.path), 1000))
            _follow_up(store, scope)
    except CollectionError as exc:
        print(collection_message(exc.code))
    except ConfigWriteError as exc:
        print(str(exc))
    except menu.PromptCancelled:
        print('Collection prompt cancelled; no further action authorized.')
    finally:
        if collector is not None and collector.ready:
            collector.cancel()
