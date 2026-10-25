"""Bounded static HTML/JSON collection under one explicitly approved origin."""
from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from typing import Callable, Generator

from core.config import CrawlConfig
from core.models import ExtractedRecord, ImportResult
from core.storage import canonical_json
from crawler.fetcher import PinnedTransport, Response
from crawler.robots import RobotsRules
from security.network_policy import CollectionError, NetworkPolicy, TargetApproval, audit_code
from security.validators import looks_restricted
from security.parser_diagnostics import OMITTED_DIAGNOSTICS, private_parser_diagnostics

EXPORT_ADVICE = "Collection stopped. Obtain an authorized export or use an officially supported, authorized API."


@dataclass
class CrawlReport:
    origin: str
    documents: list[ImportResult] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    requests: int = 0
    total_bytes: int = 0
    stop_reason: str = "completed"
    links_discovered: int = 0
    skipped_pages: int = 0
    skipped_links: int = 0

    def event(self, code: str) -> None:
        # Never log bodies, URLs/queries/paths, response headers or exception strings.
        self.events.append({"code": audit_code(code), "at": datetime.now(timezone.utc).isoformat()})

    def audit(self) -> dict:
        return {"origin": self.origin, "requests": self.requests, "body_bytes": self.total_bytes,
                "pages_collected": len(self.documents), "stop_reason": audit_code(self.stop_reason),
                "records_collected": sum(len(doc.records) for doc in self.documents),
                "links_discovered": self.links_discovered, "skipped_pages": self.skipped_pages,
                "skipped_links": self.skipped_links, "events": self.events}


def _restricted_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.hostname == "docs.google.com" and parsed.path.lstrip("/").split("/", 1)[0] in {
            "spreadsheets", "document", "presentation", "forms"}:
        raise CollectionError("interactive_document_requires_export")


def _decode(response: Response) -> tuple[str, str]:
    content_type = response.headers.get("content-type", "")
    message = Message()
    message["Content-Type"] = content_type
    media = message.get_content_type()
    if not content_type or media not in {"text/html", "application/xhtml+xml", "application/json", "text/plain"}:
        raise CollectionError("unexpected_content_type")
    charset = message.get_content_charset() or "utf-8-sig"
    if charset.lower() not in {"utf-8", "utf-8-sig", "us-ascii", "ascii", "iso-8859-1", "windows-1252"}:
        raise CollectionError("unsupported_encoding")
    try:
        return response.body.decode(charset), media
    except (UnicodeError, LookupError):
        raise CollectionError("invalid_text_encoding") from None


def _record(url: str, kind: str, title: str, text: str, fields: dict, metadata: dict) -> ExtractedRecord:
    text = unicodedata.normalize("NFC", text).strip()
    identity = canonical_json([url, kind, text, fields, metadata])
    return ExtractedRecord(hashlib.sha256(identity.encode()).hexdigest(), url, kind, title, text,
                           fields, datetime.now(timezone.utc), metadata)


def extract(response: Response, *, max_records: int, max_links: int) -> tuple[ImportResult, list[str]]:
    with private_parser_diagnostics() as diagnostics:
        document, links = _extract(response, max_records=max_records, max_links=max_links)
    if diagnostics.count:
        document = ImportResult(document.source, document.records, [*document.warnings, OMITTED_DIAGNOSTICS])
    return document, links


def _extract(response: Response, *, max_records: int, max_links: int) -> tuple[ImportResult, list[str]]:
    text, media = _decode(response)
    if any(value in response.headers.get("x-robots-tag", "").lower() for value in ("noindex", "noarchive", "none")):
        raise CollectionError("page_robots_restriction")
    if media == "application/json":
        if looks_restricted(text):
            raise CollectionError("access_restriction_detected")
        def reject(_):
            raise CollectionError("malformed_json")
        try:
            parsed = json.loads(text, parse_constant=reject)
            items = parsed if isinstance(parsed, list) else [parsed]
            if len(items) > max_records:
                raise CollectionError("record_limit")
            rows = []
            for index, item in enumerate(items):
                fields = item if isinstance(item, dict) else {"value": item}
                rows.append(_record(response.url, "web_json", "Authorized API record", canonical_json(fields),
                                    fields, {"json_pointer": f"/{index}" if isinstance(parsed, list) else ""}))
            return ImportResult(response.url, rows, []), []
        except CollectionError:
            raise
        except (ValueError, TypeError, RecursionError):
            raise CollectionError("malformed_json") from None
    if media == "text/plain":
        raise CollectionError("unexpected_content_type")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")
    for element in soup(["script", "style", "template"]):
        element.decompose()
    visible = soup.get_text("\n", strip=True)
    lowered = visible.casefold()
    if (looks_restricted(visible) or soup.find("input", attrs={"type": lambda value: value and value.lower() == "password"})
            or any(marker in lowered for marker in ("captcha", "verify you are human", "checking your browser",
                                                    "access denied", "sign in to continue", "enable javascript"))):
        raise CollectionError("access_restriction_detected")
    for meta in soup.find_all("meta"):
        if str(meta.get("name", "")).lower() in {"robots", "spiderdeckbot"}:
            if any(value in str(meta.get("content", "")).lower() for value in ("noindex", "noarchive", "none")):
                raise CollectionError("page_robots_restriction")
    title = soup.title.get_text(" ", strip=True) if soup.title else "Authorized web page"
    record = _record(response.url, "web_html", title, visible, {}, {})
    if not record.text or (soup.body is not None and not soup.body.get_text(" ", strip=True)):
        raise CollectionError("insufficient_static_text")
    links = []
    base = soup.find("base", href=True)
    base_url = urljoin(response.url, str(base["href"])) if base is not None else response.url
    nofollow = any("nofollow" in str(meta.get("content", "")).lower() for meta in soup.find_all("meta")
                   if str(meta.get("name", "")).lower() in {"robots", "spiderdeckbot"})
    if not nofollow:
        for anchor in soup.find_all("a", href=True, limit=max_links):
            if "nofollow" not in anchor.get("rel", []):
                links.append(urljoin(base_url, str(anchor["href"])))
    return ImportResult(response.url, [record] if record.text else [], []), links


class Collector:
    def __init__(self, approval: TargetApproval, config: CrawlConfig, *, transport=None,
                 clock=time.monotonic, sleep=time.sleep,
                 on_progress: Callable[[int], None] | None = None,
                 on_stage: Callable[[str], None] | None = None):
        # Revalidate config so mutable configuration cannot disable safety checks.
        self.config = CrawlConfig(**asdict(config))
        self.policy = NetworkPolicy(approval, self.config.allowed_domains)
        self.transport = transport or PinnedTransport()
        self.clock = clock
        self.sleep = sleep
        self.report = CrawlReport(approval.origin)
        self.last_request: float | None = None
        self.delay = self.config.delay_seconds
        self.deadline = 0.0
        self.visited: set[str] = set()
        self.robots = RobotsRules("", self.config.user_agent)
        self.used = False
        self.on_progress = on_progress
        self.on_stage = on_stage
        self._execution: Generator[None, None, None] | None = None
        self.ready = False
        self._finished = False
        self._preflighting = False
        self._preflight_elapsed = 0.0

    def _stage(self, label: str) -> None:
        if self.on_stage is not None:
            self.on_stage(label)

    def _wait(self, extra: float = 0) -> None:
        now = self.clock()
        wait = extra if self.last_request is None else max(extra, self.last_request + self.delay - now, 0)
        if now + wait >= self.deadline:
            raise CollectionError("duration_limit")
        if wait:
            self.sleep(wait)

    def _request(self, url: str) -> Response:
        _restricted_url(url)
        retry_after = 0.0
        for attempt in range(self.config.max_retries + 1):
            self._wait(max(2 ** (attempt - 1), retry_after) if attempt else 0)
            limit = min(self.config.max_requests, 8) if self._preflighting else self.config.max_requests
            if self.report.requests >= limit:
                raise CollectionError("request_limit")
            byte_limit = min(self.config.max_total_bytes, 4 * 1024 * 1024) if self._preflighting else self.config.max_total_bytes
            remaining = byte_limit - self.report.total_bytes
            if remaining <= 0:
                raise CollectionError("total_byte_limit")
            self.report.requests += 1
            self._stage("Fetching page")
            try:
                response = self.transport.request(url, self.policy, user_agent=self.config.user_agent,
                    timeout=min(self.config.timeout_seconds, self.deadline - self.clock()),
                    max_bytes=min(self.config.max_response_bytes, remaining, 2 * 1024 * 1024) if self._preflighting
                              else min(self.config.max_response_bytes, remaining), address_index=attempt)
            except CollectionError as exc:
                self.last_request = self.clock()
                if exc.code in {"transport_failed", "request_timeout"} and attempt < self.config.max_retries:
                    self.report.event("retry_transient_error")
                    continue
                raise
            self.last_request = self.clock()
            self.report.total_bytes += len(response.body)
            if len(response.body) > min(self.config.max_response_bytes, remaining,
                                        2 * 1024 * 1024 if self._preflighting else self.config.max_response_bytes):
                raise CollectionError("response_too_large")
            if response.status in {401, 403, 407, 451}:
                raise CollectionError("authorization_denied")
            if response.status == 429:
                raise CollectionError("rate_limited")
            if response.status in {502, 503, 504}:
                if attempt < self.config.max_retries:
                    value = response.headers.get("retry-after")
                    if value is not None:
                        try:
                            if value.isascii() and value.isdigit():
                                retry_after = int(value)
                            else:
                                stamp = parsedate_to_datetime(value)
                                if stamp.tzinfo is None:
                                    raise ValueError
                                retry_after = max(0, (stamp - datetime.now(timezone.utc)).total_seconds())
                            if retry_after > self.config.max_duration_seconds:
                                raise CollectionError("retry_after_exceeds_budget")
                        except CollectionError:
                            raise
                        except (ValueError, TypeError, OverflowError):
                            raise CollectionError("invalid_retry_after") from None
                    self.report.event("retry_upstream_unavailable")
                    continue
                raise CollectionError("upstream_unavailable")
            return response
        raise CollectionError("retry_limit")

    def _fetch(self, initial: str, *, robots: bool = False) -> Response | None:
        current = initial
        chain: set[str] = set()
        redirect_limit = min(self.config.max_redirects, 3) if self._preflighting else self.config.max_redirects
        for step in range(redirect_limit + 1):
            current = self.policy.check_url(current)
            if current in chain:
                raise CollectionError("redirect_loop")
            chain.add(current)
            if not robots:
                if not self.robots.allows(current):
                    raise CollectionError("robots_disallow")
                if current in self.visited:
                    self.report.skipped_pages += 1
                    self.report.event("already_visited")
                    return None
                self.visited.add(current)
            response = self._request(current)
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location or step >= redirect_limit:
                    raise CollectionError("redirect_limit")
                current = self.policy.check_url(urljoin(current, location))
                self.report.event("redirect")
                continue
            return response
        raise CollectionError("redirect_limit")

    def preflight(self) -> CrawlReport:
        """Approved, audited robots + seed check; pause before following links.

        At most 8 attempts, 3 redirects per chain, 20 seconds of scheduled I/O,
        2 MiB per response and 4 MiB total (or stricter configured budgets).
        DNS resolver duration retains the documented OS-level limitation.
        """
        if self.used:
            raise CollectionError("collector_already_used")
        self.used = True
        started = self.clock()
        self.deadline = started + min(self.config.max_duration_seconds, 20.0)
        self._preflighting = True
        self._execution = self._iterate()
        try:
            next(self._execution)
            self.ready = True
        except StopIteration:
            self._finished = True
        finally:
            self._preflighting = False
            self._preflight_elapsed = max(0, self.clock() - started)
        return self.report

    def cancel(self) -> None:
        if self._execution is not None:
            self._execution.close()
        if not self._finished:
            self.report.stop_reason = "cancelled"
            self.report.event("cancelled")
            self.report.event("collection_finished")
        self.ready = False
        self._finished = True

    def run(self) -> CrawlReport:
        if self.ready:
            self.ready = False
            # Human review time adds no network allowance. Count preflight's
            # active time, bytes and requests against the full run budgets.
            self.deadline = self.clock() + max(0, self.config.max_duration_seconds - self._preflight_elapsed)
        elif self.used:
            raise CollectionError("collector_already_used")
        else:
            self.used = True
            self.deadline = self.clock() + self.config.max_duration_seconds
            self._execution = self._iterate()
        try:
            for _ in self._execution:
                pass
        finally:
            self._finished = True
        return self.report

    def _iterate(self) -> Generator[None, None, None]:
        self.report.event("target_approved")
        try:
            _restricted_url(self.policy.approval.seed_url)
            self._stage("Checking access permissions")
            robots = self._fetch(self.policy.approval.origin + "/robots.txt", robots=True)
            if robots.status == 404:
                self.report.event("robots_not_found")
            elif robots.status == 200:
                text, media = _decode(robots)
                if media != "text/plain":
                    raise CollectionError("invalid_robots_response")
                if looks_restricted(text):
                    raise CollectionError("access_restriction_detected")
                self.robots = RobotsRules(text, self.config.user_agent)
                self.delay = max(self.delay, self.robots.delay)
                self.report.event("robots_loaded")
            else:
                raise CollectionError("robots_unavailable")
            queue = deque([(self.policy.approval.seed_url, 0)])
            scheduled = {self.policy.approval.seed_url}
            pages = records = 0
            while queue and pages < self.config.max_pages:
                if records >= self.config.max_records:
                    self.report.stop_reason = "record_limit"
                    self.report.event("record_limit")
                    break
                url, depth = queue.popleft()
                if url in self.visited:
                    self.report.skipped_pages += 1
                    continue
                response = self._fetch(url)
                if response is None:
                    continue
                pages += 1
                if response.status != 200:
                    raise CollectionError("unexpected_http_status")
                self._stage("Extracting content")
                document, links = extract(response, max_records=self.config.max_records - records,
                                          max_links=self.config.max_frontier + 1)
                self.report.links_discovered += len(links)
                records += len(document.records)
                if records > self.config.max_records:
                    raise CollectionError("record_limit")
                self.report.documents.append(document)
                self.report.event("page_collected")
                if self.on_progress is not None:
                    self.on_progress(len(self.report.documents))
                if depth >= self.config.max_depth:
                    self.report.skipped_links += len(links)
                    if pages == 1:
                        yield
                    continue
                frontier_full = False
                self.report.skipped_links += len(links) - len(set(links))
                ordered_links = sorted(set(links))
                for link_index, link in enumerate(ordered_links):
                    try:
                        normalized = self.policy.check_url(link)
                    except CollectionError:
                        self.report.skipped_links += 1
                        continue  # A discovered link does not authorize a new origin.
                    if normalized in scheduled or not self.robots.allows(normalized):
                        self.report.skipped_links += 1
                        continue
                    if set(urlsplit(normalized).path.lower().split("/")) & {
                            "login", "logout", "signin", "signout", "delete", "remove", "admin", "account"}:
                        self.report.skipped_links += 1
                        continue
                    if len(scheduled) >= self.config.max_frontier:
                        frontier_full = True
                        self.report.skipped_links += len(ordered_links) - link_index
                        break
                    queue.append((normalized, depth + 1))
                    scheduled.add(normalized)
                if frontier_full:
                    self.report.event("frontier_limit")
                if pages == 1:
                    yield
            if queue and self.report.stop_reason == "completed":
                self.report.skipped_pages += len(queue)
                self.report.stop_reason = "page_limit"
            elif self.report.stop_reason == "completed" and any(
                    event["code"] == "frontier_limit" for event in self.report.events):
                self.report.stop_reason = "frontier_limit"
        except CollectionError as exc:
            self.report.stop_reason = exc.code
            self.report.event(exc.code)
        except KeyboardInterrupt:
            self.report.stop_reason = "cancelled"
            self.report.event("cancelled")
        self.report.event("collection_finished")
        return self.report
