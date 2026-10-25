"""Conditional validators and references to already persisted evidence only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from core.models import ExtractedRecord, ImportResult
from core.storage import RecordStore, canonical_json
from research.models import now
from security.network_policy import CollectionError, normalize_url


def validator(value: str | None) -> str | None:
    if (not isinstance(value, str) or not value or len(value) > 1024
            or any(not 32 <= ord(char) < 127 for char in value)):
        return None
    return value


@dataclass(frozen=True)
class CacheEntry:
    document: ImportResult
    links: tuple[str, ...]
    headers: dict[str, str]


class ResearchCache:
    def __init__(self, store: RecordStore):
        self.store = store

    def headers(self, url: str) -> dict[str, str]:
        with self.store._connection() as connection:
            row = connection.execute('SELECT etag,last_modified FROM http_cache WHERE url=?',
                                     (normalize_url(url),)).fetchone()
            if row is None:
                return {}
            return {name: row[key] for key, name in (('etag','If-None-Match'),('last_modified','If-Modified-Since'))
                    if validator(row[key])}

    def get(self, url: str) -> CacheEntry | None:
        try:
            return self._get(url)
        except (ValueError,TypeError,KeyError):
            raise CollectionError('cache_validation_failed') from None

    def _get(self, url: str) -> CacheEntry | None:
        url = normalize_url(url)
        with self.store._connection() as connection:
            row = connection.execute('SELECT * FROM http_cache WHERE url=?', (url,)).fetchone()
            if row is None:
                return None
            identifiers = json.loads(row['record_ids_json'])
            if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 10000:
                raise CollectionError('cache_validation_failed')
            records, details, links = [], {}, []
            for identifier in identifiers:
                item = connection.execute('''SELECT r.*,d.cleaned_text,d.structure_json FROM '''+self.store._read_relation()+''' r
                    LEFT JOIN research_details d USING(record_id) WHERE record_id=? AND source=?''', (identifier, url)).fetchone()
                if item is None:
                    raise CollectionError('cache_validation_failed')
                record = ExtractedRecord(item['record_id'], item['source'], item['source_type'], item['title'],
                    item['text'], json.loads(item['fields_json']), datetime.fromisoformat(item['extracted_at']),
                    json.loads(item['metadata_json']))
                records.append(record)
                data = json.loads(item['structure_json'] or '{}')
                data['main_text'] = item['cleaned_text'] if item['cleaned_text'] is not None else record.text
                details[identifier] = data
                links.extend(link for link in data.get('traversable_links', []) if isinstance(link, str))
            headers = {}
            for column, name in (('etag', 'If-None-Match'), ('last_modified', 'If-Modified-Since')):
                safe = validator(row[column])
                if safe:
                    headers[name] = safe
            return CacheEntry(ImportResult(url, records, [], details=details), tuple(dict.fromkeys(links)), headers)

    def remember(self, document: ImportResult, headers: dict[str, str]) -> None:
        url = normalize_url(document.source)
        etag, modified = validator(headers.get('etag')), validator(headers.get('last-modified'))
        if not document.records or len(document.records) > 10000 or not (etag or modified):
            return
        identifiers = [record.record_id for record in document.records]
        with self.store._connection() as connection, connection:
            for identifier in identifiers:
                if not connection.execute('SELECT 1 FROM records WHERE record_id=? AND source=?', (identifier, url)).fetchone():
                    raise CollectionError('cache_validation_failed')
            connection.execute('''INSERT INTO http_cache VALUES (?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
                etag=excluded.etag,last_modified=excluded.last_modified,record_ids_json=excluded.record_ids_json,
                checked_at=excluded.checked_at''', (url, etag, modified, canonical_json(identifiers), now()))
