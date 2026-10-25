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
    pages_visited: int = 0
    relevant_pages: int = 0
    low_relevance_pages: int = 0
    unchanged_pages: int = 0
    failed_pages: int = 0
    review_pages: int = 0
    cache_validators: dict[str, dict[str, str]] = field(default_factory=dict)

    def event(self, code: str) -> None:
        # Never log bodies, URLs/queries/paths, response headers or exception strings.
        self.events.append({"code": audit_code(code), "at": datetime.now(timezone.utc).isoformat()})

    def audit(self) -> dict:
        return {"origin": self.origin, "requests": self.requests, "body_bytes": self.total_bytes,
                "pages_collected": len(self.documents), "stop_reason": audit_code(self.stop_reason),
                "records_collected": sum(len(doc.records) for doc in self.documents),
                "links_discovered": self.links_discovered, "skipped_pages": self.skipped_pages,
                "skipped_links": self.skipped_links, "events": self.events,
                "pages_visited": self.pages_visited, "relevant_pages": self.relevant_pages,
                "low_relevance_pages": self.low_relevance_pages, "unchanged_pages": self.unchanged_pages,
                "failed_pages": self.failed_pages, "review_pages": self.review_pages}


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
        document = ImportResult(document.source, document.records, [*document.warnings, OMITTED_DIAGNOSTICS], details=document.details)
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
    nofollow = any("nofollow" in str(meta.get("content", "")).lower() for meta in soup.find_all("meta")
                   if str(meta.get("name", "")).lower() in {"robots", "spiderdeckbot"})
    if not nofollow:
        from processing.content import discovered_links
        links=[target for anchor,target in discovered_links(soup,response.url,max_links)
               if 'nofollow' not in anchor.get('rel',[])]
    from processing.content import html_structure
    structure = html_structure(soup, response.url, max_links)
    structure['traversable_links'] = links
    details = {record.record_id: structure}
    return ImportResult(response.url, [record] if record.text else [], [], details=details), links


class Collector:
    def __init__(self, approval: TargetApproval, config: CrawlConfig, *, transport=None,
                 clock=time.monotonic, sleep=time.sleep,
                 on_progress: Callable[[int], None] | None = None,
                 on_stage: Callable[[str], None] | None = None, profile=None, cache=None):
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
        self.profile = profile
        self.cache = cache
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

    def _request(self, url: str, *, robots: bool = False) -> Response:
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
            headers = self.cache.headers(url) if self.cache is not None and not robots else {}
            conditional = {'conditional_headers': headers} if headers else {}
            self._stage("Fetching page")
            try:
                response = self.transport.request(url, self.policy, user_agent=self.config.user_agent,
                    timeout=min(self.config.timeout_seconds, self.deadline - self.clock()),
                    max_bytes=min(self.config.max_response_bytes, remaining, 2 * 1024 * 1024) if self._preflighting
                              else min(self.config.max_response_bytes, remaining), address_index=attempt, **conditional)
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
            response = self._request(current, robots=robots)
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
        collecting_pages = False
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
            collecting_pages = True
            if self.profile is not None:
                from crawler.frontier import TopicFrontier
                queue = TopicFrontier(self.config.max_frontier)
                queue.append((self.policy.approval.seed_url, 0))
            else:
                queue = deque([(self.policy.approval.seed_url, 0)])
            low_hops = {self.policy.approval.seed_url: 0}
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
                self.report.pages_visited += 1
                self._stage("Extracting content")
                if response.status == 304:
                    if any(value in response.headers.get('x-robots-tag','').lower() for value in ('none','noindex','noarchive')):
                        raise CollectionError('page_robots_restriction')
                    entry = self.cache.get(response.url) if self.cache is not None else None
                    if entry is None or not entry.headers:
                        raise CollectionError('cache_validation_failed')
                    document, links = entry.document, list(entry.links[:self.config.max_frontier + 1])
                    self.report.unchanged_pages += 1
                elif response.status == 200:
                    document, links = extract(response, max_records=self.config.max_records - records,
                                              max_links=self.config.max_frontier + 1)
                else:
                    raise CollectionError("unexpected_http_status")
                self.report.links_discovered += len(links)
                records += len(document.records)
                if records > self.config.max_records:
                    raise CollectionError("record_limit")
                all_records = document.records
                page_score = 0.0
                strongly_relevant = False
                link_context = {}
                if self.profile is not None:
                    from processing.content import describe
                    accepted = []
                    for record in document.records:
                        detail = describe(record, document.details.get(record.record_id))
                        for link in detail['links']:
                            link_context[link['url']] = link
                        result = self.profile.score(record.title, detail['cleaned_text'],
                            tuple(h['text'] if isinstance(h, dict) else h for h in detail['headings']))
                        strongly_relevant |= result.decision == 'relevant'
                        page_score = max(page_score, result.score)
                        if result.decision != 'low relevance':
                            accepted.append(record)
                    document = ImportResult(document.source, accepted, document.warnings, details=document.details)
                if document.records or self.profile is None:
                    self.report.documents.append(document)
                    if self.profile is None or strongly_relevant:
                        self.report.relevant_pages += 1
                    else:
                        self.report.review_pages += 1
                    if len(document.records) == len(all_records):
                        self.report.cache_validators[document.source] = {
                            key: value for key, value in response.headers.items() if key in {'etag','last-modified'}}
                        if response.status == 304:
                            for name, key in (('If-None-Match','etag'),('If-Modified-Since','last-modified')):
                                if name in entry.headers:
                                    self.report.cache_validators[document.source].setdefault(key, entry.headers[name])
                else:
                    self.report.low_relevance_pages += 1
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
                priorities = {}
                if self.profile is not None:
                    for link in ordered_links:
                        try:
                            self.policy.check_url(link)
                        except CollectionError:
                            priorities[link] = -1
                            continue
                        context = link_context.get(link, {})
                        priorities[link] = self.profile.link_priority(link, context.get('text',''),
                            context.get('context',''), page_score)
                    ordered_links.sort(key=lambda link: (-priorities[link], link))
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
                    next_low = 0 if self.profile is None or page_score >= self.profile.threshold else low_hops[url] + 1
                    if self.profile is not None:
                        if not self.profile.explore(page_score, next_low, priorities[link]):
                            self.report.skipped_links += 1
                            continue
                        queue.append((normalized, depth + 1), priorities[link])
                    else:
                        queue.append((normalized, depth + 1))
                    low_hops[normalized] = next_low
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
            if collecting_pages and exc.code not in {'request_limit','duration_limit','record_limit','total_byte_limit'}:
                self.report.failed_pages += 1
            self.report.stop_reason = exc.code
            self.report.event(exc.code)
        except KeyboardInterrupt:
            self.report.stop_reason = "cancelled"
            self.report.event("cancelled")
        self.report.event("collection_finished")
        return self.report
