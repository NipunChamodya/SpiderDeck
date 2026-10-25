"""Conservative normalized views; original extracted text is never replaced."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from urllib.parse import urljoin

from core.models import ExtractedRecord


def normalize(text: str) -> tuple[str, list[str]]:
    changed = unicodedata.normalize('NFC', text).replace('\r\n', '\n').replace('\r', '\n')
    changed = '\n'.join(line.rstrip() for line in changed.split('\n')).strip()
    changed = re.sub(r'\n{3,}', '\n\n', changed)
    transformations = [] if changed == text else ['NFC, canonical line breaks, trailing whitespace/outer whitespace and excess blank lines normalized.']
    return changed, transformations


def describe(record: ExtractedRecord, supplied: dict | None = None) -> dict:
    supplied = supplied or {}
    main = supplied.get('main_text', record.text)
    cleaned, transformations = normalize(main)
    if main != record.text:
        transformations.insert(0, 'Main/article region selected for the cleaned view; full extracted text retained separately.')
    paragraphs = [p for p in cleaned.split('\n\n') if p]
    counts = Counter(supplied.get('paragraphs') or paragraphs) if not supplied.get('structure_truncated') else Counter()
    warnings = list(supplied.get('warnings', []))
    if record.text.count('\ufffd') or any(unicodedata.category(c) == 'Cs' for c in record.text):
        warnings.append('Replacement/unencodable characters detected; inspect original source before relying on this text.')
    if record.source_type == 'pdf' and (len(record.text.strip()) < 30 or '\x00' in record.text):
        warnings.append('PDF extraction quality is uncertain. Inspect the original; no OCR was performed.')
    return {'cleaned_text': cleaned, 'headings': supplied.get('headings', []),
            'paragraphs': supplied.get('paragraphs', [])[:2000], 'lists': supplied.get('lists', [])[:500],
            'tables': supplied.get('tables', [])[:100], 'links': supplied.get('links', [])[:2000],
            'document_title': supplied.get('document_title'),
            'author': supplied.get('author'), 'publisher': supplied.get('publisher'),
            'publication_date': supplied.get('publication_date'),
            'source_category': supplied.get('source_category', 'unknown'),
            'traversable_links': supplied.get('traversable_links', [])[:2000],
            'classification_basis': supplied.get('classification_basis', 'No verified classification supplied.'),
            'location': record.metadata, 'warnings': warnings,
            'structure_truncated': bool(supplied.get('structure_truncated')),
            'duplicate_paragraphs': sum(n - 1 for n in counts.values()),
            'transformations': transformations,
            'original_sha256': hashlib.sha256(record.text.encode('utf-8')).hexdigest()}


def discovered_links(soup, url: str, max_links: int) -> list[tuple[object,str]]:
    base=soup.find('base',href=True)
    try:
        if base and len(str(base['href']))>4096:
            return []
        base_url=urljoin(url,str(base['href'])) if base else url
    except ValueError:
        return []
    if len(base_url)>4096:return []
    result=[];characters=0
    for anchor in soup.find_all('a',href=True,limit=min(max_links,10000)):
        href=str(anchor['href'])
        if len(href)>4096:continue
        try: target=urljoin(base_url,href)
        except ValueError:continue
        if len(target)>4096:continue
        characters+=len(target)
        if characters>2000000:break
        result.append((anchor,target))
    return result


def html_structure(soup, url: str, max_links: int) -> dict:
    """Called after restrictions; bound repeated/nested structural output."""
    articles=soup.find_all('article',limit=2)
    main=soup.find('main') or (articles[0] if len(articles)==1 else None) or soup.body or soup
    remaining=500000
    truncated=False
    def take(node, limit=10000):
        nonlocal remaining,truncated
        if remaining<=0:
            truncated=True;return ''
        value=node.get_text(' ',strip=True)
        cap=min(remaining,limit)
        if len(value)>cap:truncated=True
        value=value[:cap];remaining-=len(value)
        return value
    headings=[]
    for node in main.find_all(re.compile(r'^h[1-6]$'),limit=200):
        headings.append({'level':int(node.name[1]),'text':take(node)})
    paragraphs=[]
    for node in main.find_all('p',limit=2000):
        if remaining<=0:truncated=True;break
        paragraphs.append(take(node))
    lists=[]
    for node in main.find_all(['ul','ol'],limit=500):
        if remaining<=0:truncated=True;break
        lists.append(take(node))
    tables=[]
    for table in main.find_all('table',limit=100):
        if remaining<=0:truncated=True;break
        rows=[]
        for row in table.find_all('tr',limit=200):
            if remaining<=0:truncated=True;break
            cells=[]
            for cell in row.find_all(['th','td'],limit=100):
                if remaining<=0:truncated=True;break
                cells.append(take(cell,2000))
            rows.append(cells)
        tables.append(rows)
    links=[]
    for anchor,target in discovered_links(soup,url,max_links):
        text=take(anchor,500)
        context=take(anchor.parent,1000) if anchor.parent.name in {'p','li'} else ''
        links.append({'url':target,'text':text,'context':context})
    def meta(*names):
        for node in soup.find_all('meta',limit=500):
            if str(node.get('name',node.get('property',''))).lower() in names:
                return str(node.get('content',''))[:1000] or None
        return None
    date=meta('citation_publication_date','article:published_time','date')
    time=soup.find('time',datetime=True)
    if date is None and time is not None:date=str(time['datetime'])[:1000]
    return {'main_text':main.get_text('\n',strip=True),'headings':headings,'paragraphs':paragraphs,
        'lists':lists,'tables':tables,'links':links,'author':meta('author','citation_author'),
        'publisher':meta('og:site_name','citation_journal_title'),'publication_date':date,
        'structure_truncated':truncated,
        'warnings':['Structural previews reached a size/count budget; full extracted text is retained.'] if truncated else []}


def matching_excerpt(row: dict, keyword: str, width: int = 300) -> tuple[str,str]:
    query=unicodedata.normalize('NFC',keyword).casefold()
    for name in ('cleaned_text','text','title'):
        value=unicodedata.normalize('NFC',row[name])
        position=value.casefold().find(query)
        if position>=0:
            offset=0;original_position=0
            for index,char in enumerate(value):
                if offset>=position:
                    original_position=index;break
                offset+=len(char.casefold())
            start=max(0,original_position-80)
            return value[start:start+width],name
    return row['cleaned_text'][:width],'FTS token/phrase index preview'
