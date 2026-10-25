"""Project management and readable source-attributed terminal evidence."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from core.config import AppConfig
from core.text import safe_multiline
from core.storage import RecordStore, SearchFilters, StorageError
from research.models import ResearchProject, profile_fingerprint
from research.relevance import NOTICE, suggest_keywords
from research.storage import ProjectStore
from ui import menu
from ui.display import terminal_text


def _terms(message: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in menu.prompt_text(message).split(',') if part.strip())


def create(api: ProjectStore) -> ResearchProject | None:
    title = menu.prompt_text('Research title (blank cancels):')
    if not title.strip(): return None
    description = menu.prompt_text('Optional description:')
    suggested = suggest_keywords(title)
    print('Literal title suggestions, not verified concepts: ' + ', '.join(suggested))
    terms = _terms('Reviewed keywords, comma-separated (blank uses title suggestions):') or suggested
    excluded = _terms('Excluded topics, comma-separated (optional):')
    mode = menu.prompt_choice('Research mode:', ['Balanced', 'Strict', 'Discovery'])
    if not mode: return None
    project = ResearchProject(title,description,terms,excluded,mode.lower())
    if menu.confirm('Create this research project?'):
        api.create(project)
        print('Research project created.')
        return project
    return None


def read(row: dict, project: ResearchProject) -> None:
    print('\nSPIDERDECK RESEARCH DOCUMENT\n')
    for label,value in [('Project',project.title),('Document',row['title']),('Source',row['source']),
                        ('Type',row['source_type']),('Evidence ID',row['record_id'][:12]),('Collected',row['extracted_at']),
                        ('Last associated/checked',row['linked_at'])]:
        print(label + ': ' + terminal_text(value,1000))
    print(f'Relevance: {row["score"]:g}/100. ' + NOTICE)
    analysis = row['analysis']
    print('Matched: ' + terminal_text(', '.join(analysis['matched']),1000))
    print('Missing: ' + terminal_text(', '.join(analysis['missing']),1000))
    print('Excluded-topic matches: '+terminal_text(', '.join(analysis['excluded_matches']) or '(none)',1000))
    components=analysis['components']
    print(f'Body coverage {components["coverage"]:.0%}; title {components["title"]:.0%}; '
          f'headings {components["headings"]:.0%}; body phrases {components["phrase"]:.0%}; '
          f'cosine {components["cosine"]:.3f}; exclusion penalty {components["exclusion_penalty"]:g} points.')
    print(terminal_text(analysis['explanation'],1500))
    if analysis.get('profile_hash') != profile_fingerprint(project):
        print('Assessment uses earlier project settings. Choose Reassess stored evidence to update it.')
    structure = row['structure']
    print('Source category: ' + terminal_text(row.get('category') or 'unknown'))
    print('Classification: ' + terminal_text(row.get('basis') or 'Unverified; no peer-review claim.'))
    for key in ('document_title','author','publisher','publication_date'):
        if structure.get(key): print(key.replace('_',' ').title()+' (source-declared): '+terminal_text(structure[key],500))
    for warning in structure.get('warnings',[]): print('Quality notice: '+terminal_text(warning,500))
    for key in ('page','worksheet','row','paragraph','table','json_pointer'):
        if key in row['metadata']:print(key.replace('_',' ').title()+': '+terminal_text(str(row['metadata'][key]),500))
    print('\nSUMMARY\nNo generated summary available.\n\nCONTENT')
    text = row['cleaned_text']
    for index in range(0,len(text),3000):
        print(safe_multiline(text[index:index+3000],3000))
        if index+3000 < len(text) and not menu.confirm('Read next content page?'): break
    print('\nREFERENCES\nOriginal source: '+terminal_text(row['source'],1000))
    if menu.confirm('Inspect original extracted text (before cleaning), up to 3000 characters?'):
        print(safe_multiline(row['text'],3000))
        print('The complete original is retained in SQLite and JSON exports.')


def browse(api: ProjectStore, project: ResearchProject, *, search: bool = False, source: str = '') -> None:
    keyword = menu.prompt_text('Search project (blank lists all):') if search else ''
    source = source or (menu.prompt_text('Source contains (blank for all):') if search else '')
    kind = menu.prompt_text('Document type (blank for all):') if search else ''
    since = menu.prompt_text('Collected since YYYY-MM-DD (blank for all):') if search else ''
    until = menu.prompt_text('Collected until YYYY-MM-DD (blank for all):') if search else ''
    sort = menu.prompt_choice('Sort results:', ['relevance','date','source']) if search else 'relevance'
    if not sort: return
    offset = 0
    while True:
        rows = api.search(project.project_id,SearchFilters(keyword,source,kind),since=since,until=until,sort=sort,offset=offset)
        if not rows:
            print('No further matching research records.'); return
        labels = [f'{index+1}: {terminal_text(row["title"],100)} | {row["score"]:g}/100 | {row["record_id"][:12]} | {terminal_text(row["source"],100)}'
                  for index,row in enumerate(rows)]
        choice = menu.prompt_choice('Stored evidence (scores are heuristic):',labels+['Next page','Back'])
        if not choice or choice == 'Back': return
        if choice == 'Next page': offset+=len(rows);continue
        row = rows[labels.index(choice)]
        # Show a real matching excerpt near the literal keyword.
        print('Matching excerpt ('+row['excerpt_source']+'): '+terminal_text(row['excerpt'],300))
        read(row,project)
        if menu.confirm('Set a user-assessed source category? This does not verify peer review.'):
            category = menu.prompt_choice('Source category:', ['academic publication','university website','government publication',
                                                             'technical documentation','blog','unknown'])
            if category:
                basis = menu.prompt_text('Evidence note (do not include credentials):')
                api.classify_source(row['source'],category,basis)


def export(api: ProjectStore, project: ResearchProject) -> None:
    from exporters.research import export_project
    filename = menu.prompt_text('Project export filename under output (blank cancels):')
    if not filename: return
    filters=SearchFilters();since=until=''
    if menu.confirm('Filter this project export by keyword, source, type or collection date?'):
        from ui.records import prompt_filters
        filters=prompt_filters()
        since=menu.prompt_text('Collected since YYYY-MM-DD (blank for all):')
        until=menu.prompt_text('Collected until YYYY-MM-DD (blank for all):')
    suffix = Path(filename).suffix.lower().lstrip('.')
    if not suffix:
        suffix = menu.prompt_choice('Export format:', ['md','json','csv'])
        if not suffix: return
        filename += '.'+suffix
    try:
        count = export_project(api,project,filename,suffix,filters=filters,since=since,until=until)
    except FileExistsError:
        if not menu.confirm('An export already exists. Keep a private backup and explicitly replace this private export?'): return
        count = export_project(api,project,filename,suffix,overwrite=True,filters=filters,since=since,until=until)
    print(f'Exported {count} research records to '+terminal_text(filename))


def edit(api: ProjectStore, project: ResearchProject) -> ResearchProject:
    choice = menu.prompt_choice('Edit research settings:', ['Title','Description','Keywords','Excluded topics','Mode','Thresholds','Scoring limit','Search mode','Back'])
    changes = {}
    if choice in ('Title','Description'):
        changes[choice.lower()] = menu.prompt_text('New '+choice.lower()+':')
    elif choice in ('Keywords','Excluded topics'):
        changes['keywords' if choice=='Keywords' else 'excluded'] = _terms('New comma-separated terms:')
    elif choice == 'Mode':
        mode=menu.prompt_choice('Mode:',['balanced','strict','discovery'])
        if mode: changes['mode']=mode
    elif choice == 'Thresholds':
        print('Threshold order must be Strict >= Balanced >= Discovery. Scores are heuristic, not probabilities.')
        settings=dict(project.settings)
        for mode in ('strict','balanced','discovery'):
            raw=menu.prompt_text(f'{mode.title()} threshold (0–100; blank keeps current):')
            if raw: settings[mode+'_threshold']=float(raw)
        changes['settings']=settings
    elif choice == 'Scoring limit':
        raw=menu.prompt_text('Maximum scored characters per record (1000–2000000; blank cancels):')
        if raw:changes['settings']={**project.settings,'max_scoring_chars':int(raw)}
    elif choice == 'Search mode':
        mode=menu.prompt_choice('Literal substring preserves Unicode behavior; FTS uses token/phrase matching if available:', ['literal','fts'])
        if mode: changes['settings']={**project.settings,'search_mode':mode}
    if changes:
        updated=replace(project,**changes)
        if menu.confirm('Save research settings? Existing assessments remain until explicitly reassessed.'):
            api.update(updated)
            return api.get(project.project_id)
    return project


def dashboard(api: ProjectStore, project: ResearchProject, config: AppConfig, get_store: Callable[[],RecordStore], config_path: Path, root: Path, *, security_ok: bool = False) -> None:
    while True:
        project=api.get(project.project_id)
        stats=api.dashboard(project)
        print('\nSPIDERDECK RESEARCH DASHBOARD\n'+terminal_text(project.title,300))
        print('Created: '+project.created_at+'; last modified: '+project.updated_at)
        print(f'Mode: {project.mode}; sources: {stats["sources"]}; records: {stats["records"]}; '
              f'relevant: {stats["relevant"]}; exact content duplicates: {stats["exact_duplicates"]}; failures: {stats["failures"]}')
        if stats['stale_assessments']:
            print(f'{stats["stale_assessments"]} assessments use earlier settings; choose Reassess to update.')
        if stats['review_records']:
            print(f'{stats["review_records"]} records need manual review because scoring was bounded.')
        print('Coverage: matched stored records; Missing=0, Limited=1, Moderate=2–4, Strong=5+. Not proof of completeness.')
        for term,coverage in stats['coverage'].items():
            print(f'  {terminal_text(term)}: {coverage["label"]} ({coverage["records"]} records)')
        if project.archived: print('This project is archived. Unarchive before adding sources.')
        choice=menu.prompt_choice('Project actions:', ['Collect authorized websites','Import documents','Browse evidence','Search project',
            'Export findings','Edit research settings','Reassess stored evidence','Collection history','Archive / unarchive','Delete project','Back'])
        if not choice or choice=='Back':return
        try:
            if choice=='Collect authorized websites':
                if not security_ok:
                    print('Web collection is disabled because the startup security self-check failed.');continue
                if project.archived: print('Unarchive this project first.');continue
                from ui import collection
                print('Each seed URL gets its own hostname/access/start confirmations and bounded run.')
                while True:
                    collection.run(config.crawl,get_store,config_path=config_path,
                                   output_dir=root/Path(config.output.dir).expanduser(),project=project)
                    if not menu.confirm('Add another authorized starting URL to this project?'):break
            elif choice=='Import documents':
                if project.archived: print('Unarchive this project first.');continue
                from ui import importing
                importing.run(config.imports,get_store,project=project)
            elif choice in ('Browse evidence','Search project'):
                browse(api,project,search=choice=='Search project')
            elif choice=='Export findings': export(api,project)
            elif choice=='Edit research settings': project=edit(api,project)
            elif choice=='Reassess stored evidence':
                if menu.confirm('Reassess linked records with current project settings? Original evidence is preserved.'):
                    print(f'Reassessed {api.reassess(project)} linked records.')
            elif choice=='Collection history':
                for run in api.history(project.project_id):
                    print(terminal_text(f'{run["finished_at"]} | {run["status"]} | {run["source"]}',1000))
                    import json
                    for key,value in json.loads(run['summary_json']).items():
                        print(f'  {key.replace("_"," ")}: {value}')
            elif choice=='Archive / unarchive':
                if menu.confirm('Change this project archive state?'):
                    api.update(replace(project,archived=not project.archived))
            elif choice=='Delete project':
                if menu.prompt_text('Type DELETE to delete only this project and its associations:')=='DELETE' and menu.confirm('Permanently delete this project? Shared source evidence will remain.'):
                    api.delete(project.project_id,confirmed=True);return
        except menu.PromptCancelled:
            print('Action cancelled. Previously committed evidence remains saved.')
        except (StorageError,ValueError,OSError,TypeError,KeyError):
            print('Research action failed safely. Check the selected values, output permissions and database state; existing evidence was preserved.')


def run(config: AppConfig,get_store: Callable[[],RecordStore],config_path: Path,root: Path, *, security_ok: bool = False) -> None:
    api=ProjectStore(get_store())
    while True:
        choice=menu.prompt_choice('Research projects:', ['Create project','Open project','Open archived project','Back'])
        if not choice or choice=='Back':return
        try:
            if choice=='Create project': project=create(api)
            else:
                projects=api.list(include_archived=choice=='Open archived project')
                if choice=='Open archived project': projects=[p for p in projects if p.archived]
                labels=[f'{terminal_text(p.title,120)} | {p.project_id[:8]}' for p in projects]
                selected=menu.prompt_choice('Choose project:',labels)
                project=projects[labels.index(selected)] if selected else None
            if project: dashboard(api,project,config,get_store,config_path,root,security_ok=security_ok)
        except menu.PromptCancelled:
            print('Project form cancelled; no incomplete edit was saved.')
        except (StorageError,ValueError,OSError,TypeError,KeyError):
            print('Project action failed safely. Check fields and output permissions; no existing evidence was deleted.')
