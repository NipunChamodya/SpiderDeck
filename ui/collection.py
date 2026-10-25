"""Explicit per-run target approval and local persistence/auditing."""
from __future__ import annotations

import json
from typing import Callable
from uuid import uuid4
from urllib.parse import urlsplit

from core.config import CrawlConfig
from core.storage import RecordStore, StorageError
from crawler.collector import Collector, EXPORT_ADVICE
from security.filesystem import new_output_text
from security.network_policy import CollectionError, approve_target, hostname, normalize_url, origin
from ui import menu
from ui.progress import operation


def run(config: CrawlConfig, get_store: Callable[[], RecordStore]) -> None:
    requested = menu.prompt_url("Public HTML or approved public JSON API URL:")
    if not requested:
        return
    try:
        url = normalize_url(requested)
        if urlsplit(url).hostname not in {hostname(domain) for domain in config.allowed_domains}:
            raise CollectionError("domain_not_allowlisted")
        scope = origin(url)
        print(f"Target scope: {scope}; at most {config.max_pages} pages, depth {config.max_depth}.")
        print("This performs automated GET requests, including robots.txt and linked pages on this origin.")
        print("Authentication alone does not grant permission for bulk extraction. No login session will be used.")
        if not menu.confirm(f"I have explicit permission for this automated collection on {scope}:"):
            print("Target not approved; no requests made.")
            return
        approval = approve_target(url, config.allowed_domains, authorized=True)
        store = get_store()
        audit_name = f"crawl-audit-{uuid4().hex}.json"
        # Verify output access and reserve an exclusive private audit file before network activity.
        with new_output_text(store.root, audit_name) as audit_file:
            with operation("Collecting approved pages; respecting robots and rate limits", unit="pages") as progress:
                report = Collector(approval, config, on_progress=progress.set_completed).run()
            saved = duplicates = 0
            try:
                for document in report.documents:
                    summary = store.save_import(document)
                    saved += summary.inserted
                    duplicates += summary.duplicates
            except StorageError:
                report.stop_reason = "storage_failed"
                report.event("storage_failed")
            payload = report.audit()
            payload.update(records_saved=saved, duplicate_identifiers=duplicates)
            json.dump(payload, audit_file, ensure_ascii=False, sort_keys=True, indent=2)
            audit_file.write("\n")
        print(f"Collected {len(report.documents)} pages; saved {saved} records; skipped {duplicates} duplicate identifiers.")
        print(f"Outcome: {report.stop_reason}. Audit saved as {audit_name} under output.")
        if report.stop_reason in {"page_limit", "frontier_limit", "request_limit", "duration_limit", "record_limit", "total_byte_limit"}:
            print("A configured collection budget was reached. Narrow the target or review the configured limits.")
        elif report.stop_reason not in {"completed", "cancelled"}:
            print(EXPORT_ADVICE)
        print("Previously accepted pages may be retained if a later page stopped the run.")
    except CollectionError as exc:
        print(f"Collection unavailable: {exc.code}. Configure the exact hostname and explicitly approve the target.")
