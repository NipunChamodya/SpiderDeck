"""Transactional, local SQLite repository with literal Unicode search."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.models import ExtractedRecord, ImportResult
from rank.models import ResearchIdea
from security.filesystem import (
    check_owned_file, open_output_directory, output_directory, verify_directory,
)
from security.validators import UnsafePathError, safe_output_path

SCHEMA_VERSION = 3
APPLICATION_ID = 0x5350444B  # SPDK
DATABASE_NAME = "spiderdeck.sqlite3"


class StorageError(ValueError):
    """A safe, user-facing storage failure."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def content_hash(record: ExtractedRecord) -> str:
    """Ignore source/location/time; retain format, text and structured fields."""
    value = canonical_json([record.source_type, record.text, record.fields])
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


@dataclass(frozen=True)
class SearchFilters:
    keyword: str = ""
    source: str = ""
    source_type: str = ""
    exact_source: bool = False


@dataclass(frozen=True)
class SaveSummary:
    inserted: int
    duplicates: int
    content_duplicates: int
    reimported: bool


class RecordStore:
    def __init__(self, output_dir: str | Path):
        try:
            self.root = output_directory(output_dir)
            self.path = safe_output_path(self.root, DATABASE_NAME)
        except (OSError, UnsafePathError) as exc:
            raise StorageError("Cannot use the configured output directory or database path safely.") from exc
        self._initialize()

    @contextmanager
    def _connection(self, *, initialize: bool = False) -> Iterator[sqlite3.Connection]:
        """Keep checked descriptors open while SQLite uses the private pathname."""
        yielded = False
        try:
            with open_output_directory(self.root) as directory_fd:
                created = False
                try:
                    descriptor = os.open(DATABASE_NAME, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                         dir_fd=directory_fd)
                except FileNotFoundError:
                    if not initialize:
                        raise StorageError("Database disappeared; restart before writing more data.")
                    descriptor = os.open(DATABASE_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL
                                         | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
                    created = True
                try:
                    check_owned_file(descriptor)
                    for suffix in ("-journal", "-wal", "-shm"):
                        try:
                            sidecar = os.open(DATABASE_NAME + suffix, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                              dir_fd=directory_fd)
                        except FileNotFoundError:
                            continue
                        try:
                            check_owned_file(sidecar)
                        finally:
                            os.close(sidecar)
                    verify_directory(self.root, directory_fd)
                    uri = self.path.as_uri() + "?mode=rw"
                    connection = sqlite3.connect(uri, uri=True, timeout=5)
                    try:
                        connection.row_factory = sqlite3.Row
                        connection.execute("PRAGMA trusted_schema=OFF")
                        connection.execute("PRAGMA foreign_keys=ON")
                        connection.execute("PRAGMA temp_store=MEMORY")
                        connection.execute("PRAGMA cache_size=-2048")
                        connection.create_function("unicode_fold", 1, _fold, deterministic=True)
                        if created:
                            self._create_schema(connection)
                        elif initialize:
                            self._migrate_schema(connection)
                        self._check_schema(connection)
                        yielded = True
                        yield connection
                    finally:
                        connection.close()
                finally:
                    os.close(descriptor)
        except (sqlite3.Error, OSError, UnsafePathError) as exc:
            # The caller may write an export while holding a read snapshot.
            # Preserve its filesystem errors (notably FileExistsError) so the
            # UI can request explicit replacement; database errors stay sanitized.
            if yielded and isinstance(exc, (OSError, UnsafePathError)):
                raise
            raise StorageError(
                "Cannot access the database safely. Check output permissions, disk space and locks; "
                "existing files were not replaced."
            ) from exc

    def _initialize(self) -> None:
        with self._connection(initialize=True) as connection:
            if connection.execute('PRAGMA foreign_key_check').fetchone():
                raise StorageError('Database reference integrity failed. Restore a trusted backup.')
            if connection.execute('SELECT 1 FROM record_copies c JOIN record_copies nested '
                                  'ON nested.record_id=c.canonical_id LIMIT 1').fetchone():
                raise StorageError('Unexpected chained content references. Restore a trusted backup.')

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE records (
                record_id TEXT PRIMARY KEY NOT NULL,
                source TEXT NOT NULL, source_type TEXT NOT NULL,
                title TEXT NOT NULL, text TEXT NOT NULL, fields_json TEXT NOT NULL,
                extracted_at TEXT NOT NULL, metadata_json TEXT NOT NULL,
                content_hash TEXT NOT NULL
            )""")
            connection.execute("CREATE INDEX records_content_hash ON records(content_hash)")
            connection.execute("CREATE INDEX records_type ON records(source_type)")
            connection.execute("CREATE INDEX records_order ON records(source, source_type, record_id)")
            connection.execute("""CREATE TABLE imports (
                source TEXT NOT NULL, manifest_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL, record_count INTEGER NOT NULL,
                PRIMARY KEY (source, manifest_hash)
            )""")
            RecordStore._create_ideas_table(connection)
            from research.schema import create
            create(connection)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _create_ideas_table(connection: sqlite3.Connection) -> None:
        connection.execute("""CREATE TABLE ideas (
            idea_id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL,
            description TEXT NOT NULL, keywords_json TEXT NOT NULL,
            domain TEXT, keyword_weights_json TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")

    def _migration_backup(self, connection: sqlite3.Connection, version: int) -> None:
        from uuid import uuid4
        identity=uuid4().hex
        name = f'migration-v{version}-{identity}.sqlite3'
        pending = f'.migration-pending-{identity}.sqlite3'
        with open_output_directory(self.root) as directory:
            fd = os.open(pending, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                check_owned_file(fd)
                target = sqlite3.connect((self.root / pending).as_uri() + '?mode=rw', uri=True)
                try:
                    import time
                    deadline=time.monotonic()+120
                    def progress(status: int, remaining: int, total: int) -> None:
                        if time.monotonic()>deadline:
                            raise StorageError('Migration backup exceeded its time budget. No migration was applied.')
                    connection.backup(target,pages=128,progress=progress,sleep=.05)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise StorageError('Migration backup failed integrity validation; no migration applied.')
                finally:
                    target.close()
                os.fsync(fd)
                verify_directory(self.root, directory)
                os.link(pending,name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
                os.fsync(directory)
            finally:
                os.close(fd)
                os.unlink(pending,dir_fd=directory)

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version not in (1, 2):
            return
        self._check_schema(connection, expected_version=version)
        # A read transaction gives backup + DDL the same snapshot. An upgrade
        # conflict fails/rolls back rather than replacing an existing database.
        with connection:
            connection.execute('BEGIN')
            self._check_schema(connection, expected_version=version)
            preserved_tables=('records','imports','ideas') if version==2 else ('records','imports')
            counts = tuple(connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                           for table in preserved_tables)
            self._migration_backup(connection, version)
            if version == 1:
                self._create_ideas_table(connection)
            from research.schema import create
            create(connection)
            if counts != tuple(connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                               for table in preserved_tables):
                raise StorageError('Migration record-count verification failed; migration rolled back.')
            connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            self._check_schema(connection)

    @staticmethod
    def _check_schema(connection: sqlite3.Connection, *, expected_version: int = SCHEMA_VERSION) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        app = connection.execute("PRAGMA application_id").fetchone()[0]
        if app != APPLICATION_ID or version != expected_version:
            raise StorageError("Unrecognized database or unsupported schema version. No migration was applied.")
        # Imported databases are not supported. Refuse executable schema objects.
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchone():
            raise StorageError("Unexpected database schema objects; use an untampered SpiderDeck database.")
        virtual = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND upper(sql) LIKE '%VIRTUAL TABLE%'").fetchall()
        for name, sql in virtual:
            expected = "CREATE VIRTUAL TABLE research_fts USING fts5(title, text, content='')"
            if expected_version < 3 or name != 'research_fts' or ' '.join(sql.split()).lower() != expected.lower():
                raise StorageError('Unexpected virtual database table; use an untampered SpiderDeck database.')
        required = {
            "records": {"record_id", "source", "source_type", "title", "text", "fields_json",
                        "extracted_at", "metadata_json", "content_hash"},
            "imports": {"source", "manifest_hash", "imported_at", "record_count"},
        }
        if expected_version >= 2:
            required["ideas"] = {"idea_id", "title", "description", "keywords_json", "domain",
                                 "keyword_weights_json", "archived", "created_at", "updated_at"}
        if expected_version >= 3:
            from research.schema import TABLE_COLUMNS
            required.update(TABLE_COLUMNS)
        for table, columns in required.items():
            actual = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if actual != columns:
                raise StorageError("Unexpected database table layout. No migration was applied.")

    def add_idea(self, idea: ResearchIdea) -> None:
        idea = ResearchIdea(**idea.to_dict())
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM ideas WHERE idea_id=?", (idea.idea_id,)).fetchone():
                raise StorageError("Idea identifier already exists; use edit for an existing idea.")
            if connection.execute("SELECT count(*) FROM ideas WHERE archived=0").fetchone()[0] >= 1000:
                raise StorageError("At most 1000 active ideas are supported; remove an unused idea first.")
            connection.execute("INSERT INTO ideas VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)", (
                idea.idea_id, idea.title, idea.description, canonical_json(idea.keywords), idea.domain,
                canonical_json(idea.keyword_weights), timestamp, timestamp))

    def update_idea(self, idea: ResearchIdea) -> None:
        idea = ResearchIdea(**idea.to_dict())
        with self._connection() as connection, connection:
            cursor = connection.execute("""UPDATE ideas SET title=?, description=?, keywords_json=?,
                domain=?, keyword_weights_json=?, updated_at=? WHERE idea_id=? AND archived=0""", (
                idea.title, idea.description, canonical_json(idea.keywords), idea.domain,
                canonical_json(idea.keyword_weights), datetime.now(timezone.utc).isoformat(), idea.idea_id))
            if cursor.rowcount != 1:
                raise StorageError("Active idea not found; reload the idea list.")

    def archive_idea(self, idea_id: str) -> None:
        """Remove from active use without physically deleting its saved contents."""
        with self._connection() as connection, connection:
            cursor = connection.execute("UPDATE ideas SET archived=1, updated_at=? WHERE idea_id=? AND archived=0",
                                        (datetime.now(timezone.utc).isoformat(), idea_id))
            if cursor.rowcount != 1:
                raise StorageError("Active idea not found; reload the idea list.")

    def list_ideas(self) -> list[ResearchIdea]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM ideas WHERE archived=0 ORDER BY title, idea_id")
            try:
                return [ResearchIdea(
                    title=row["title"], description=row["description"],
                    keywords=json.loads(row["keywords_json"]), domain=row["domain"],
                    keyword_weights=json.loads(row["keyword_weights_json"]), idea_id=row["idea_id"],
                ) for row in rows]
            except (ValueError, TypeError) as exc:
                raise StorageError("A stored idea is malformed; restore a trusted database backup.") from exc

    @staticmethod
    def _read_relation() -> str:
        return """(SELECT r.record_id,r.source,r.source_type,r.title,
            CASE WHEN c.record_id IS NULL THEN r.text ELSE original.text END AS text,
            CASE WHEN c.record_id IS NULL THEN r.fields_json ELSE original.fields_json END AS fields_json,
            r.extracted_at,r.metadata_json,r.content_hash FROM main.records r
            LEFT JOIN record_copies c ON c.record_id=r.record_id
            LEFT JOIN main.records original ON original.record_id=c.canonical_id)"""

    def save_import(self, result: ImportResult) -> SaveSummary:
        with self._connection() as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            return self._save_import(connection, result)

    @staticmethod
    def _save_import(connection: sqlite3.Connection, result: ImportResult) -> SaveSummary:
        digest = hashlib.sha256()
        for identifier in sorted(record.record_id for record in result.records):
            digest.update(identifier.encode("utf-8") + b"\x00")
        manifest = digest.hexdigest()
        inserted = duplicates = content_duplicates = 0
        reimported = connection.execute(
            "SELECT 1 FROM imports WHERE source=? AND manifest_hash=?",
            (result.source, manifest),
        ).fetchone() is not None
        for record in result.records:
            if record.source != result.source:
                raise StorageError("Record source does not match its import provenance.")
            # Serialize only what persistence needs. Public to_dict() still
            # returns an independent deep copy; storage need not copy it first.
            fields = canonical_json(record.fields)
            metadata = canonical_json(record.metadata)
            previous = connection.execute("SELECT * FROM " + RecordStore._read_relation() + " WHERE record_id=?",
                                          (record.record_id,)).fetchone()
            if previous is not None:
                # Never let an ID collision silently discard different content.
                if any(previous[key] != value for key, value in zip(
                    ("source", "source_type", "title", "text", "fields_json", "metadata_json"),
                    (record.source, record.source_type, record.title, record.text, fields, metadata),
                )):
                    raise StorageError("Record identifier collision; import rolled back without replacing data.")
                duplicates += 1
                continue
            values = (record.record_id, record.source, record.source_type, record.title,
                      record.text, fields, record.extracted_at.isoformat().replace("+00:00", "Z"),
                      metadata, content_hash(record))
            duplicate = connection.execute("SELECT r.record_id,coalesce(c.canonical_id,r.record_id) AS canonical_id "
                "FROM records r LEFT JOIN record_copies c ON c.record_id=r.record_id WHERE r.content_hash=? LIMIT 1",
                (values[-1],)).fetchone()
            canonical_id = None
            if duplicate:
                canonical_id = duplicate['canonical_id']
                original = connection.execute('SELECT text,fields_json,source_type FROM records WHERE record_id=?',
                                              (canonical_id,)).fetchone()
                if (original['text'],original['fields_json'],original['source_type']) != (record.text,fields,record.source_type):
                    raise StorageError('Content hash collision; original evidence was not replaced.')
                content_duplicates += 1
                values = (*values[:4], '', '{}', *values[6:])
            connection.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            if canonical_id:
                connection.execute('INSERT INTO record_copies VALUES (?,?)',(record.record_id,canonical_id))
            inserted += 1
        connection.execute("""INSERT INTO imports VALUES (?, ?, ?, ?)
                              ON CONFLICT(source, manifest_hash) DO NOTHING""",
                           (result.source, manifest, datetime.now(timezone.utc).isoformat(),
                            len(result.records)))
        return SaveSummary(inserted, duplicates, content_duplicates, reimported)

    @staticmethod
    def _where(filters: SearchFilters) -> tuple[str, list[str]]:
        clauses: list[str] = []
        parameters: list[str] = []
        if filters.keyword:
            clauses.append("instr(unicode_fold(title || char(10) || text), ?) > 0")
            parameters.append(_fold(filters.keyword))
        if filters.source:
            if filters.exact_source:
                clauses.append("source = ?")
                parameters.append(filters.source)
            else:
                clauses.append("instr(unicode_fold(source), ?) > 0")
                parameters.append(_fold(filters.source))
        if filters.source_type:
            clauses.append("source_type = ?")
            parameters.append(_fold(filters.source_type).lstrip("."))
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def count(self, filters: SearchFilters = SearchFilters()) -> int:
        where, parameters = self._where(filters)
        with self._connection() as connection:
            relation = self._read_relation() if filters.keyword else "records"
            return connection.execute("SELECT count(*) FROM " + relation + where, parameters).fetchone()[0]

    def iter_records(self, filters: SearchFilters = SearchFilters(), *,
                     limit: int | None = None, offset: int = 0) -> Iterator[ExtractedRecord]:
        if offset < 0 or (limit is not None and limit <= 0):
            raise ValueError("Search offset must be nonnegative and limit must be positive.")
        where, parameters = self._where(filters)
        query = "SELECT * FROM " + self._read_relation() + where + " ORDER BY source, source_type, record_id"
        query_parameters: list[Any] = list(parameters)
        query += " LIMIT ? OFFSET ?"
        query_parameters.extend([-1 if limit is None else limit, offset])
        with self._connection() as connection:
            cursor = connection.execute(query, query_parameters)
            try:
                for row in cursor:
                    yield ExtractedRecord(
                        row["record_id"], row["source"], row["source_type"], row["title"],
                        row["text"], json.loads(row["fields_json"]),
                        datetime.fromisoformat(row["extracted_at"]), json.loads(row["metadata_json"]),
                    )
            finally:
                cursor.close()

    def search(self, filters: SearchFilters = SearchFilters(), *,
               limit: int = 50, offset: int = 0) -> list[ExtractedRecord]:
        return list(self.iter_records(filters, limit=limit, offset=offset))
