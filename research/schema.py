"""Additive schema v3; no triggers, record rewrites, or mandatory FTS dependency."""
import sqlite3

TABLE_COLUMNS = {
    'projects': {'project_id', 'title', 'description', 'keywords_json', 'excluded_json', 'mode',
                 'settings_json', 'created_at', 'updated_at', 'archived'},
    'project_records': {'project_id', 'record_id', 'score', 'analysis_json', 'linked_at', 'profile_hash'},
    'record_copies': {'record_id','canonical_id'},
    'research_fts_map': {'id','record_id'},
    'research_profiles': {'profile_hash','profile_json'},
    'research_details': {'record_id', 'cleaned_text', 'structure_json'},
    'research_sources': {'source', 'category', 'basis', 'first_seen', 'last_seen'},
    'collection_runs': {'run_id', 'project_id', 'source', 'started_at', 'finished_at', 'status', 'summary_json'},
    'http_cache': {'url', 'etag', 'last_modified', 'record_ids_json', 'checked_at'},
}


def has_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute('CREATE VIRTUAL TABLE temp.spiderdeck_fts_probe USING fts5(text)')
        connection.execute('DROP TABLE temp.spiderdeck_fts_probe')
        return True
    except sqlite3.OperationalError as exc:
        if 'no such module' not in str(exc).lower():
            raise
        return False


def create(connection: sqlite3.Connection) -> None:
    statements = [
        '''CREATE TABLE projects (project_id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL,
        description TEXT NOT NULL, keywords_json TEXT NOT NULL, excluded_json TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('strict','balanced','discovery')), settings_json TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL CHECK(archived IN (0,1)))''',
        'CREATE TABLE record_copies (record_id TEXT PRIMARY KEY NOT NULL REFERENCES records(record_id), canonical_id TEXT NOT NULL REFERENCES records(record_id), CHECK(record_id<>canonical_id))',
        'CREATE INDEX record_copy_target ON record_copies(canonical_id)',
        'CREATE TABLE research_fts_map (id INTEGER PRIMARY KEY, record_id TEXT UNIQUE NOT NULL REFERENCES records(record_id))',
        'CREATE TABLE research_profiles (profile_hash TEXT PRIMARY KEY NOT NULL, profile_json TEXT NOT NULL)',
        '''CREATE TABLE project_records (project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        record_id TEXT NOT NULL REFERENCES records(record_id), score REAL NOT NULL CHECK(score>=0 AND score<=100),
        analysis_json TEXT NOT NULL, linked_at TEXT NOT NULL, profile_hash TEXT NOT NULL REFERENCES research_profiles(profile_hash), PRIMARY KEY(project_id,record_id))''',
        'CREATE INDEX project_record_date ON project_records(project_id,linked_at DESC,record_id)',
        'CREATE INDEX project_record_score ON project_records(project_id,score DESC,record_id)',
        'CREATE INDEX project_profile_hash ON project_records(profile_hash)',
        'CREATE INDEX project_record_reverse ON project_records(record_id,project_id)',
        '''CREATE TABLE research_details (record_id TEXT PRIMARY KEY NOT NULL REFERENCES records(record_id),
        cleaned_text TEXT, structure_json TEXT NOT NULL)''',
        '''CREATE TABLE research_sources (source TEXT PRIMARY KEY NOT NULL, category TEXT NOT NULL,
        basis TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)''',
        '''CREATE TABLE collection_runs (run_id TEXT PRIMARY KEY NOT NULL,
        project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL, source TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT NOT NULL, status TEXT NOT NULL, summary_json TEXT NOT NULL)''',
        'CREATE INDEX runs_project_date ON collection_runs(project_id,finished_at DESC)',
        '''CREATE TABLE http_cache (url TEXT PRIMARY KEY NOT NULL, etag TEXT, last_modified TEXT,
        record_ids_json TEXT NOT NULL, checked_at TEXT NOT NULL)''',
        'CREATE INDEX records_date ON records(extracted_at,record_id)',
        'CREATE INDEX records_location ON records(source,source_type,metadata_json,record_id)',
    ]
    for statement in statements:
        connection.execute(statement)
    if has_fts(connection):
        connection.execute("CREATE VIRTUAL TABLE research_fts USING fts5(title, text, content='')")
