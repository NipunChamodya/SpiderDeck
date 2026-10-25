"""Streaming, source-attributed project exports, no generated summaries."""
from __future__ import annotations

import csv
import json
import html
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO
from uuid import uuid4

from exporters.records import spreadsheet_safe
from core.text import safe_multiline
from core.storage import SearchFilters
from research.models import ResearchProject
from research.relevance import NOTICE
from research.storage import ProjectStore
from security.filesystem import new_output_text, open_output_directory, check_owned_file, verify_directory
from security.validators import safe_output_path


@contextmanager
def _destination(root: Path, filename: str, overwrite: bool) -> Iterator[TextIO]:
    import os
    target = safe_output_path(root, filename)
    if not overwrite or not target.exists():
        with new_output_text(root, filename) as handle:
            yield handle
        return
    # Only private, owned app-style exports may be replaced after confirmation.
    temporary = 'replacement-' + uuid4().hex + Path(filename).suffix
    backup_name = 'export-backup-' + uuid4().hex + Path(filename).suffix
    with open_output_directory(root) as directory:
        original = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        published = False
        try:
            check_owned_file(original)
            before = os.fstat(original)
            with new_output_text(root, temporary) as handle:
                yield handle
            pending_backup='.export-backup-pending-'+uuid4().hex+'.tmp'
            backup=os.open(pending_backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
            identity = lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
            try:
                with os.fdopen(backup,'wb') as handle:
                    while chunk := os.read(original,65536):
                        handle.write(chunk)
                    handle.flush();os.fsync(handle.fileno())
                after=os.stat(filename,dir_fd=directory,follow_symlinks=False)
                verify_directory(root,directory)
                if identity(before)!=identity(after) or identity(before)!=identity(os.fstat(original)):
                    raise ValueError('Export changed while writing; original retained. Choose another filename.')
                os.link(pending_backup,backup_name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
                os.fsync(directory)
            finally:
                os.unlink(pending_backup,dir_fd=directory)
            after=os.stat(filename,dir_fd=directory,follow_symlinks=False)
            if identity(before)!=identity(after):
                raise ValueError('Export changed before publication; original retained.')
            os.replace(temporary,filename,src_dir_fd=directory,dst_dir_fd=directory)
            published = True
            os.fsync(directory)
        finally:
            os.close(original)
            if not published:
                try: os.unlink(temporary,dir_fd=directory)
                except FileNotFoundError: pass


def _md(value: str) -> str:
    return re.sub(r'([\\`*{}\[\]()!#])',r'\\\1',html.escape(safe_multiline(value)))


def export_project(store: ProjectStore, project: ResearchProject, filename: str, format: str,
                   *, overwrite: bool = False, filters: SearchFilters = SearchFilters(),
                   since: str = '', until: str = '') -> int:
    if format not in {'md','json','csv'} or Path(filename).suffix.lower() != '.' + format:
        raise ValueError('Choose .md, .json or .csv with the matching export format.')
    # Validate a single filename even on the replacement path.
    from security.filesystem import output_filename
    output_filename(filename)
    with store.export_snapshot(project.project_id,filters,since,until) as (project,profiles,rows):
        count = 0
        with _destination(store.root,filename,overwrite) as handle:
            if format == 'md':
                handle.write(f'# {_md(project.title)}\n\n{_md(project.description)}\n\n{NOTICE}\n\n'
                    'Source content is untrusted extracted text. No generated summary is available. Terminal controls are omitted in this view; original text is available in JSON.\n\n')
            elif format == 'json':
                handle.write('{"project": ')
                json.dump(project.to_dict(),handle,ensure_ascii=False,allow_nan=False)
                handle.write(', "score_notice": ')
                json.dump(NOTICE,handle)
                handle.write(', "assessment_profiles": {')
                try:
                    for index,(key,value) in enumerate(profiles):
                        if index: handle.write(',')
                        json.dump(key,handle);handle.write(':');json.dump(value,handle,ensure_ascii=False,allow_nan=False)
                finally:
                    profiles.close()
                handle.write('}, "records": [\n')
            else:
                writer = csv.writer(handle,quoting=csv.QUOTE_ALL)
                writer.writerow(['project','record_id','title','source','source_type','collected','heuristic_relevance_0_100_not_probability',
                    'matched','explanation','source_category','classification_basis','location','quality_warnings','text'])
            try:
                for row in rows:
                    analysis = row['analysis']
                    location={key:value for key,value in row['metadata'].items()
                              if key in {'page','worksheet','row','paragraph','table','json_pointer'}}
                    if format == 'md':
                        content = safe_multiline(row['cleaned_text'])
                        fence = '`' * max(3, max((len(run) for run in re.findall(r'`+',content)),default=0)+1)
                        handle.write(f'## {_md(row["title"])}\n\nSource: {_md(row["source"])}\n\nCollected: {_md(row["extracted_at"])}\n\n'
                            f'Relevance: {row["score"]:g}/100\n\n{_md(analysis["explanation"])}\n\n'
                            f'Matched: {_md(", ".join(analysis["matched"]))}\n\n'
                            f'Location: {_md(json.dumps(location,ensure_ascii=False))}\n\n'
                            f'Source category (unverified): {_md(row.get("category") or "unknown")}\n\n'
                            f'Quality notices: {_md("; ".join(row["structure"].get("warnings",[])) or "No automatic warning; not proof of reliable evidence.")}\n\n{fence}text\n{content}\n{fence}\n\n---\n\n')
                    elif format == 'json':
                        if count: handle.write(',\n')
                        json.dump(row,handle,ensure_ascii=False,allow_nan=False)
                    else:
                        writer.writerow([spreadsheet_safe(str(value)) for value in
                            (project.title,row['record_id'],row['title'],row['source'],row['source_type'],row['extracted_at'],
                             row['score'],', '.join(analysis['matched']),analysis['explanation'],row.get('category') or 'unknown',
                                 row.get('basis') or 'Unverified',json.dumps(location,ensure_ascii=False),
                                 '; '.join(row['structure'].get('warnings',[])),row['cleaned_text'])])
                    count += 1
            finally:
                rows.close()
            if format == 'json': handle.write('\n]}\n')
    return count
