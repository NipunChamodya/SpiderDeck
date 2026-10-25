"""Project associations over shared, unchanged legacy record rows."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator
from uuid import uuid4

from core.models import ExtractedRecord, ImportResult
from core.storage import RecordStore, SearchFilters, StorageError, canonical_json
from processing.content import describe
from research.models import ResearchProject, now, profile_settings, profile_fingerprint
from research.relevance import ResearchProfile


@dataclass(frozen=True)
class ProjectSave:
    inserted: int
    duplicates: int
    content_duplicates: int
    linked: int
    skipped: int
    updated: int
    reimported: bool = False


class ProjectStore:
    def __init__(self, records: RecordStore):
        self.records = records
        self.root = records.root

    @staticmethod
    def _project(row: sqlite3.Row) -> ResearchProject:
        return ResearchProject(row['title'], row['description'], json.loads(row['keywords_json']),
            json.loads(row['excluded_json']), row['mode'], json.loads(row['settings_json']),
            row['project_id'], row['created_at'], row['updated_at'], bool(row['archived']))

    def create(self, project: ResearchProject) -> None:
        project = ResearchProject(**project.to_dict())
        with self.records._connection() as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT count(*) FROM projects').fetchone()[0] >= 1000:
                raise StorageError('At most 1000 projects are supported; archive or explicitly delete unused projects.')
            connection.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)',
                (project.project_id, project.title, project.description, canonical_json(project.keywords),
                 canonical_json(project.excluded), project.mode, canonical_json(project.settings),
                 project.created_at, project.updated_at, int(project.archived)))

    def get(self, project_id: str) -> ResearchProject:
        with self.records._connection() as connection:
            row = connection.execute('SELECT * FROM projects WHERE project_id=?', (project_id,)).fetchone()
            if row is None:
                raise StorageError('Project not found; reload the project list.')
            return self._project(row)

    def list(self, *, include_archived: bool = False) -> list[ResearchProject]:
        with self.records._connection() as connection:
            query = 'SELECT * FROM projects' + ('' if include_archived else ' WHERE archived=0')
            return [self._project(row) for row in connection.execute(query + ' ORDER BY title,project_id')]

    def update(self, project: ResearchProject) -> None:
        project = ResearchProject(**project.to_dict())
        with self.records._connection() as connection, connection:
            cursor = connection.execute('''UPDATE projects SET title=?,description=?,keywords_json=?,excluded_json=?,
                mode=?,settings_json=?,updated_at=?,archived=? WHERE project_id=?''',
                (project.title, project.description, canonical_json(project.keywords), canonical_json(project.excluded),
                 project.mode, canonical_json(project.settings), now(), int(project.archived), project.project_id))
            if cursor.rowcount != 1:
                raise StorageError('Project not found; reload the project list.')
        # Existing scores remain evidence of their original assessment, not
        # silently recomputed by an edit. The UI exposes explicit reassessment.

    def delete(self, project_id: str, *, confirmed: bool = False) -> None:
        if confirmed is not True:
            raise StorageError('Explicit project deletion confirmation is required.')
        with self.records._connection() as connection, connection:
            connection.execute('DELETE FROM projects WHERE project_id=?', (project_id,))
            connection.execute('DELETE FROM research_profiles WHERE NOT EXISTS (SELECT 1 FROM project_records WHERE project_records.profile_hash=research_profiles.profile_hash)')
        # ON DELETE CASCADE removes associations only; raw records/sources survive.

    @staticmethod
    def _fts(connection: sqlite3.Connection) -> bool:
        return connection.execute("SELECT 1 FROM sqlite_master WHERE name='research_fts'").fetchone() is not None

    def ingest(self, project: ResearchProject | None, result: ImportResult, *, retain_low: bool = False) -> ProjectSave:
        if project is not None:
            current = self.get(project.project_id)
            if current.archived:
                raise StorageError('Open an active project before collecting records.')
            if profile_settings(current) != profile_settings(project):
                raise StorageError('Project settings changed. Reload the project before collection.')
        profile = ResearchProfile(project) if project else None
        fingerprint = profile_fingerprint(project) if project else None
        encoded_profile = canonical_json(profile_settings(project)) if project else None
        prepared = []
        for record in result.records:
            detail = describe(record, result.details.get(record.record_id))
            detail['warnings'].extend(w for w in result.warnings if not w.startswith('Page ') or w.startswith(f'Page {record.metadata.get("page")}:'))
            analysis = profile.score(record.title, detail['cleaned_text'],
                tuple(h['text'] if isinstance(h, dict) else h for h in detail['headings'])) if profile else None
            if analysis is None or retain_low or analysis.decision != 'low relevance':
                prepared.append((record, detail, analysis))
        filtered = ImportResult(result.source, [r for r, _, _ in prepared], result.warnings)
        linked = updated = 0
        with self.records._connection() as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            if project:
                row = connection.execute('SELECT * FROM projects WHERE project_id=?', (project.project_id,)).fetchone()
                if row is None or bool(row['archived']) or profile_settings(self._project(row)) != profile_settings(project):
                    raise StorageError('Project changed while scoring. Reload and retry.')
            versions = {record.record_id for record, _, _ in prepared if connection.execute(
                'SELECT 1 FROM records WHERE source=? AND source_type=? AND metadata_json=? AND record_id<>? LIMIT 1',
                (record.source, record.source_type, canonical_json(record.metadata), record.record_id)).fetchone()}
            if project:
                connection.execute('INSERT OR IGNORE INTO research_profiles VALUES (?,?)',
                    (fingerprint,encoded_profile))
            summary = self.records._save_import(connection, filtered)
            fts = self._fts(connection)
            for record, detail, analysis in prepared:
                cleaned = detail.pop('cleaned_text')
                if len(canonical_json(detail).encode()) > 8 * 1024 * 1024:
                    raise StorageError('Structured content exceeds the storage limit; split the source.')
                cursor = connection.execute('INSERT OR IGNORE INTO research_details VALUES (?,?,?)',
                    (record.record_id, cleaned if cleaned != record.text else None, canonical_json(detail)))
                if cursor.rowcount and fts:
                    mapping = connection.execute('INSERT INTO research_fts_map(record_id) VALUES (?)',(record.record_id,))
                    connection.execute('INSERT INTO research_fts(rowid,title,text) VALUES (?,?,?)',
                                       (mapping.lastrowid, record.title, cleaned))
                timestamp = now()
                connection.execute('''INSERT INTO research_sources VALUES (?,?,?,?,?) ON CONFLICT(source)
                    DO UPDATE SET last_seen=excluded.last_seen''',
                    (record.source, detail['source_category'], detail['classification_basis'], timestamp, timestamp))
                if project:
                    previous = connection.execute('SELECT 1 FROM project_records WHERE project_id=? AND record_id=?',
                                                  (project.project_id, record.record_id)).fetchone()
                    connection.execute('''INSERT INTO project_records VALUES (?,?,?,?,?,?) ON CONFLICT(project_id,record_id)
                        DO UPDATE SET score=excluded.score,analysis_json=excluded.analysis_json,linked_at=excluded.linked_at,profile_hash=excluded.profile_hash''',
                        (project.project_id, record.record_id, analysis.score,
                         canonical_json({**analysis.to_dict(), 'profile_hash': fingerprint}), timestamp, fingerprint))
                    linked += int(previous is None)
                    updated += int(previous is None and record.record_id in versions)
            if project:
                connection.execute('UPDATE projects SET updated_at=? WHERE project_id=?',(now(),project.project_id))
        return ProjectSave(summary.inserted, summary.duplicates, summary.content_duplicates,
                           linked, len(result.records) - len(prepared), updated, summary.reimported)

    def history(self, project_id: str, *, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError('History limit must be between 1 and 100.')
        with self.records._connection() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM collection_runs WHERE project_id=? '
                'ORDER BY finished_at DESC,run_id LIMIT ?', (project_id, limit))]

    def record_run(self, project_id: str | None, source: str, status: str, summary: dict, *, started_at: str | None = None) -> None:
        from security.network_policy import audit_code
        # Only counts enter history summaries, never response headers/cookies or exception strings.
        allowed = {'pages_visited','body_bytes','requests','pages_collected','records_collected','links_discovered',
            'skipped_pages','skipped_links','relevant_pages','low_relevance_pages','unchanged_pages','failed_pages',
            'review_pages','failed_documents','new_records','updated_records','linked','low_relevance','exact_duplicates','content_duplicates','extracted'}
        counts = {key: value for key, value in summary.items() if key in allowed and type(value) is int and 0 <= value <= 10**9}
        with self.records._connection() as connection, connection:
            connection.execute('INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?)',
                (uuid4().hex, project_id, source, started_at or now(), now(), audit_code(status), canonical_json(counts)))

    def _query(self, project_id: str, filters: SearchFilters, since: str, until: str, use_fts: bool) -> tuple[str, list]:
        where, parameters = self.records._where(filters)
        clauses = [where.removeprefix(' WHERE ')] if where else []
        clauses.append('record_id IN (SELECT record_id FROM project_records WHERE project_id=?)')
        parameters.append(project_id)
        for value, op in ((since, '>='), (until, '<=')):
            if value:
                date.fromisoformat(value)
                comparison = '>=' if op == '>=' else '<'
                boundary = value + ('T00:00:00' if op == '>=' else 'T24:00:00')
                clauses.append('record_id IN (SELECT record_id FROM project_records WHERE project_id=? AND linked_at ' + comparison + ' ?)')
                parameters.extend((project_id,boundary))
        if use_fts and filters.keyword:
            # Literal quoted phrase prevents FTS operators/query syntax injection.
            literal = '"' + filters.keyword.replace('"', '""') + '"'
            clauses = [c for c in clauses if 'title ||' not in c]
            parameters = parameters[1:]
            clauses.append('record_id IN (SELECT record_id FROM research_fts_map WHERE id IN (SELECT rowid FROM research_fts WHERE research_fts MATCH ?))')
            parameters.append(literal)
        return ' WHERE ' + ' AND '.join(clauses), parameters

    def search(self, project_id: str, filters: SearchFilters = SearchFilters(), *, since: str = '', until: str = '',
               sort: str = 'relevance', limit: int = 20, offset: int = 0) -> list[dict]:
        if sort not in {'relevance', 'date', 'source'} or not 1 <= limit <= 100 or offset < 0:
            raise ValueError('Use a valid sort and a page size from 1 to 100.')
        project = self.get(project_id)
        with self.records._connection() as connection:
            where, params = self._query(project_id, filters, since, until,
                project.settings['search_mode'] == 'fts' and self._fts(connection))
            order = {'relevance': 'pr.score DESC,r.source,r.record_id', 'date': 'pr.linked_at DESC,r.record_id',
                     'source': 'r.source,r.record_id'}[sort]
            query = '''SELECT r.*,pr.score,pr.analysis_json,pr.linked_at,d.cleaned_text,d.structure_json,
                s.category,s.basis FROM (SELECT * FROM ''' + self.records._read_relation() + where + ''') r
                JOIN project_records pr ON pr.record_id=r.record_id AND pr.project_id=?
                LEFT JOIN research_details d ON d.record_id=r.record_id
                LEFT JOIN research_sources s ON s.source=r.source ORDER BY ''' + order + ' LIMIT ? OFFSET ?'
            rows=[self._research_row(row) for row in connection.execute(query, (*params, project_id, limit, offset))]
            from processing.content import matching_excerpt
            for row in rows:
                row['excerpt'],row['excerpt_source']=matching_excerpt(row,filters.keyword)
            return rows

    @staticmethod
    def _research_row(row) -> dict:
        result = dict(row)
        for key in ('fields_json', 'metadata_json', 'analysis_json', 'structure_json'):
            result[key.removesuffix('_json')] = json.loads(result.pop(key) or '{}')
        result['cleaned_text'] = result['cleaned_text'] if result['cleaned_text'] is not None else result['text']
        result['excerpt'] = result['cleaned_text'][:300]
        return result

    def _read_findings(self, connection: sqlite3.Connection, project: ResearchProject, filters: SearchFilters, since: str, until: str) -> Iterator[dict]:
        where, params = self._query(project.project_id,filters,since,until,
            project.settings['search_mode']=='fts' and self._fts(connection))
        query = """SELECT r.*,pr.score,pr.analysis_json,pr.linked_at,d.cleaned_text,d.structure_json,
            s.category,s.basis FROM (SELECT * FROM """+self.records._read_relation()+where+""") r
            JOIN project_records pr ON pr.record_id=r.record_id AND pr.project_id=?
            LEFT JOIN research_details d ON d.record_id=r.record_id
            LEFT JOIN research_sources s ON s.source=r.source ORDER BY pr.score DESC,r.source,r.record_id"""
        cursor=connection.execute(query,(*params,project.project_id))
        try:
            for row in cursor:yield self._research_row(row)
        finally:cursor.close()

    def iter_findings(self, project_id: str, filters: SearchFilters = SearchFilters(), *, since: str = '', until: str = '') -> Iterator[dict]:
        with self.export_snapshot(project_id,filters,since,until) as (_,profiles,rows):
            yield from rows

    @staticmethod
    def _read_profiles(connection: sqlite3.Connection, project_id: str) -> Iterator[tuple[str,dict]]:
        cursor=connection.execute('SELECT profile_hash,profile_json FROM research_profiles WHERE profile_hash IN '
            '(SELECT profile_hash FROM project_records WHERE project_id=?) ORDER BY profile_hash',(project_id,))
        try:
            for row in cursor:yield row[0],json.loads(row[1])
        finally:cursor.close()

    @contextmanager
    def export_snapshot(self, project_id: str, filters: SearchFilters = SearchFilters(), since: str = '', until: str = ''):
        with self.records._connection() as connection:
            connection.execute('BEGIN')
            item=connection.execute('SELECT * FROM projects WHERE project_id=?',(project_id,)).fetchone()
            if item is None:raise StorageError('Project disappeared; reload before export.')
            project=self._project(item)
            profiles=self._read_profiles(connection,project_id)
            rows=self._read_findings(connection,project,filters,since,until)
            try:yield project,profiles,rows
            finally:
                rows.close();profiles.close();connection.rollback()

    def dashboard(self, project: ResearchProject) -> dict:
        with self.records._connection() as connection:
            row = connection.execute('''SELECT count(*) records,count(DISTINCT r.source) sources,
                count(*)-count(DISTINCT r.content_hash) exact_duplicates,
                sum(pr.score>=?) relevant FROM project_records pr JOIN records r USING(record_id)
                WHERE project_id=?''', (ResearchProfile(project).threshold, project.project_id)).fetchone()
            failures = connection.execute("SELECT count(*) FROM collection_runs WHERE project_id=? AND status NOT IN ('completed','cancelled','page_limit','frontier_limit','request_limit','duration_limit','record_limit','total_byte_limit')", (project.project_id,)).fetchone()[0]
            result = dict(row)
            result['relevant'] = result['relevant'] or 0
            result['failures'] = failures
            result['coverage'] = {}
            matches: dict[str, int] = {}
            fingerprint = profile_fingerprint(project)
            result['relevant'] = result['stale_assessments'] = result['review_records'] = 0
            for record in connection.execute('SELECT analysis_json FROM project_records WHERE project_id=?', (project.project_id,)):
                analysis = json.loads(record[0])
                result['relevant'] += int(analysis.get('decision') == 'relevant')
                result['review_records'] += int(analysis.get('decision') == 'review')
                result['stale_assessments'] += int(analysis.get('profile_hash') != fingerprint)
                for term in analysis.get('matched', []):
                    matches[term] = matches.get(term, 0) + 1
            for term in ResearchProfile(project).terms:
                count = matches.get(term, 0)
                result['coverage'][term] = {'records': count, 'label': 'Strong' if count >= 5 else 'Moderate' if count >= 2 else 'Limited' if count else 'Missing'}
            return result

    def classify_source(self, source: str, category: str, basis: str) -> None:
        if category not in {'academic publication', 'university website', 'government publication',
                            'technical documentation', 'blog', 'unknown'} or not 1 <= len(basis) <= 1000:
            raise ValueError('Select a source category and supply an evidence note; peer review is not inferred.')
        with self.records._connection() as connection, connection:
            connection.execute('UPDATE research_sources SET category=?,basis=? WHERE source=?',
                               (category, 'User-supplied, unverified: ' + basis, source))

    def reassess(self, project: ResearchProject) -> int:
        last = ''
        total = 0
        while True:
            with self.records._connection() as connection:
                rows = connection.execute('SELECT r.* FROM '+self.records._read_relation()+' r JOIN project_records pr USING(record_id) '
                    'WHERE pr.project_id=? AND r.record_id>? ORDER BY r.record_id LIMIT 20',
                    (project.project_id, last)).fetchall()
                batch = []
                for row in rows:
                    record = ExtractedRecord(row['record_id'],row['source'],row['source_type'],row['title'],row['text'],
                        json.loads(row['fields_json']),datetime.fromisoformat(row['extracted_at']),json.loads(row['metadata_json']))
                    detail = connection.execute('SELECT * FROM research_details WHERE record_id=?',(record.record_id,)).fetchone()
                    structure = json.loads(detail['structure_json']) if detail else {}
                    if detail:
                        structure['main_text'] = detail['cleaned_text'] if detail['cleaned_text'] is not None else record.text
                    batch.append((record,structure))
            if not batch:
                return total
            for record, detail in batch:
                self.ingest(project, ImportResult(record.source,[record],[],details={record.record_id:detail}),retain_low=True)
            total += len(batch)
            last = rows[-1]['record_id']

    def profiles(self, project_id: str) -> Iterator[tuple[str,dict]]:
        with self.records._connection() as connection:
            yield from self._read_profiles(connection,project_id)
