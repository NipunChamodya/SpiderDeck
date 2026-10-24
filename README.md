# SpiderDeck

Local-first research document intelligence for Python 3.13 (tested on macOS).
SpiderDeck imports authorized local documents without network requests or remote AI.
Imports persist in SQLite and support browsing, search and CSV/JSON exports.
Research ideas and explainable offline supervisor ranking are available.
Website collection is not implemented yet.

## Installation

```zsh
bash install.sh
source .venv/bin/activate
python verify.py
python spiderdeck.py --no-fx
```

The existing installer installs the repository's full dependency list, including
future-phase dependencies. Browser installation is optional and unnecessary for
local imports. No new runtime dependency was added for local importing.
`--setup` is not an available command. `--no-fx` disables cosmetic animations.

## Importing

Choose **2) Import a local document**, then enter a readable file path:

```text
Local document to import: /Users/me/Documents/supervisors.xlsx
Imported 12 records; saved 12 new records; skipped 0 duplicate identifiers.
```

Inputs may be outside `output/`. Folder recursion is not supported. Imports
are atomic: a failed import returns no partial records. Documents are not
logged. After a successful menu import, records are committed to SQLite and
survive restarts. Browse/search shows limited text previews. The importer API
remains usable without persistence:

```python
from handlers.local import import_document

result = import_document("/Users/me/Documents/supervisors.csv")
for record in result.records:
    payload = record.to_dict()  # JSON-compatible values and UTC timestamp
```

Supported formats:

| Format | Behavior |
| --- | --- |
| CSV | UTF-8/BOM, comma delimiter, first row headers; one record per data row |
| XLSX | All worksheets, first row headers; cached values, no formula evaluation |
| PDF | Text per page; low-text pages produce warnings; no OCR |
| DOCX | Paragraphs and table rows; no embedded content execution |
| JSON | Root array items or one root value; nested fields preserved |
| TXT / Markdown | UTF-8/BOM text, one record per document |
| HTML / HTM | Local text only; scripts/styles removed; external assets never fetched |

Blank/duplicate CSV and XLSX headers get deterministic unique names. Blank
rows are skipped; inconsistent row widths are rejected. Spreadsheet cell values
are normalized to strings. Empty documents return warnings. DOCX tables use
positional column names. PDF text extraction permission flags are respected.

Records contain source path, format, title, normalized NFC text, fields, UTC
extraction time, and location metadata (row/worksheet, page, paragraph/table or
JSON pointer). IDs are SHA-256 of canonical JSON containing the absolute source,
format, text, fields and location, excluding extraction time. Reimporting the
same content at the same path produces the same IDs; moving a file changes them.
Separate content hashes identify equal format/text/fields across locations;
these copies are reported and retained with their source provenance.
Timestamps serialize as ISO 8601 UTC with a `Z` suffix.

## Storage, search and exports

The database is `spiderdeck.sqlite3` inside `[output].dir` (default `output/`).
Relative output directories resolve against the application directory, not your
shell working directory. The database is created on the first import, browse,
search or export operation; startup, security checks and `--dry-run` do not
create it. Use an output directory owned by you, without group/other write
permissions. Database files must have mode `0600`; SpiderDeck refuses unsafe
permissions rather than changing existing files automatically.

Menu workflows retain arrow-key navigation:

- **2) Import** commits the complete document in one transaction.
- **3) Browse** previews 20 records at a time.
- **4) Search** combines keyword, source-path substring and exact document-type filters.
- **5) Research ideas and supervisor ranking** manages saved ideas and compares them locally.
- **9) Export** applies the same filters and asks for a new `.csv` or `.json` filename.
- **8) Quit** closes the application; saved records remain available next time.

Search is casefolded, NFC-normalized literal substring matching over record title
and text, with support for Sinhala, Tamil and English. `%`, `_` and SQL syntax
have no special meaning. All filters are combined with AND. Empty filters select
all records. Results sort deterministically by source, type and record ID.
This implementation uses the portable SQLite search path, without FTS5; searches
scan candidate records and may slow down for very large databases.

Reimporting unchanged records skips their stable identifiers and preserves the
original extraction timestamps. A manifest of source and record IDs detects a
previously imported record set. Changed records are added; old versions are
retained. Equal content at another source/location is flagged, not discarded.
There is no automatic deletion, replacement, version comparison or byte-level
unchanged-file shortcut: reimports still parse the input. Schema version 2 and
an application ID identify SpiderDeck databases. Recognized version 1 databases
receive a transactional, additive migration that creates the ideas table;
existing records and import manifests are preserved. Unrelated databases, unknown
versions and existing unrelated files are refused without modification.
An older Phase B application cannot open the upgraded database; use the current code.

Exports stream one record at a time, with no database-sized Python list. JSON
preserves the record schema, nested fields and Unicode. CSV uses a fixed column
schema with JSON in `fields` and `metadata`, quotes every cell and prefixes risky
spreadsheet cells with an apostrophe. CSV protection intentionally changes those
cells; JSON preserves exact content. Do not strip these prefixes before opening
CSV in a spreadsheet. Export only to a single filename directly under output;
subdirectories and absolute export paths are rejected. Existing names are never
overwritten, including symlinks. Failed exports do not publish partial files.
Exports include local source paths and document text; share them deliberately.

```python
from core.storage import RecordStore, SearchFilters
from exporters.records import export_records
from handlers.local import import_document

store = RecordStore("output")
summary = store.save_import(import_document("/Users/me/Documents/supervisors.csv"))
filters = SearchFilters(keyword="vision", source_type="csv")
print(summary.inserted, store.count(filters))
export_records(store.iter_records(filters), store.root, "vision.json", "json")
```

API callers choose their output directory explicitly; relative API paths use the
caller's current directory. For a stopped application, back up the database by
copying it to a safe location. Do not copy an actively written SQLite file as a
backup. Database import/restore, encryption and record deletion workflows are not provided.

## Research ideas and supervisor ranking

Choose **5)**, then **Create idea**, **List ideas**, **Edit idea**, **Remove idea**,
or **Compare ideas**. Ideas store a title, description, keywords, optional domain,
and optional per-keyword weights in SQLite. A title is required; missing
information remains visible in the comparison. Edit prompts keep a field when
left blank; enter `-` to clear it. Keyword weights are JSON, e.g. `{"vision": 2}`,
and must refer to listed keywords. Removal archives an idea instead of deleting
its stored contents. There is a limit of 1,000 active saved ideas.

Compare uses checkboxes (Space to select, Enter to confirm) for one or several
ideas, then the existing keyword/source/type filters to choose imported records.
The terminal shows the top results per idea: name when available, score, shared
terms, every source document, score components, reasoning and uncertainty.
Optional comparison JSON exports preserve selected ideas, filters, weights,
rankings and source record identifiers. Export publication uses the same safe,
private, no-overwrite output mechanism as document exports.

The four initial FYP topics are provided as editable **example data** in
[examples/research_ideas.json](examples/research_ideas.json). They are never
hardcoded into the ranker or automatically inserted. To save them explicitly,
run this from the repository with the virtual environment active (adapt the
output path if configured differently):

```python
import json
from pathlib import Path
from core.storage import RecordStore
from rank.models import ResearchIdea

store = RecordStore("output")
existing = {idea.title for idea in store.list_ideas()}
for entry in json.loads(Path("examples/research_ideas.json").read_text(encoding="utf-8")):
    if entry["title"] not in existing:
        store.add_idea(ResearchIdea(**entry))
        existing.add(entry["title"])
```

### Methodology and interpretation

The default is scikit-learn TF-IDF with unigram/bigram features and cosine
similarity ([TF-IDF documentation](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html),
[cosine documentation](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.cosine_similarity.html)).
The vocabulary/IDF is fit on the selected candidate documents; each
idea's title and description are transformed against that fixed vocabulary.
Unicode tokens preserve combining marks for Sinhala and Tamil. There is no
translation, stemming, semantic model, network call or model download.
Changing the corpus can change the scores, so scores from different comparisons
are not directly calibrated against each other.

Recognized expertise fields are preferred over full row text. Default name
aliases include `Name`, `Supervisor` and `Supervisor Name`; expertise aliases
include `Expertise`, `Research Interests` and `Research Areas`. These alias lists,
plus email, affiliation and domain aliases, can be configured in `[ranking]`.
Local-language column headers can be added explicitly. No name or expertise is
invented from free text: missing fields are reported, and unstructured documents
remain document-level candidates. Headers, footers and whole-document context
are not reconstructed across imported paragraphs/pages.

Exact copies are grouped before fitting TF-IDF. Named rows are also grouped by
email when available, otherwise name plus affiliation, otherwise name plus
source. Copied content connects groups while retaining every source and record
ID. Each distinct text chunk contributes once. This prevents copied rows from
boosting a supervisor's rank. Name-based grouping is unverified and can combine
same-named people; inspect source records, especially contradictory versions.
Historical imported records remain eligible unless excluded with filters.

Optional scoring blends three components using a normalized weighted mean:

```text
score = (text_weight * cosine_similarity
       + keyword_weight * weighted_keyword_coverage
       + domain_weight * structured_domain_match) / sum(component_weights)
```

Keyword coverage uses token-boundary phrases in expertise/fallback text and the
idea's keyword weights (default 1, zero disables a keyword). Domain matching is
binary phrase matching against recognized structured domain fields only. These
are lexical heuristics. Text, keyword and domain features can be correlated; they are
blended rather than independently added as confidence evidence. Default weights
are text=1, keyword=0, domain=0. Keywords/domain influence scores only when their
component weights are positive; per-keyword weights alone do not enable that
component. Missing inputs score zero without silently renormalizing the weights.
All-zero or nonfinite component weights are refused.

**Scores are heuristic relevance estimates, not verified supervisor suitability.**
They do not establish availability, willingness or qualifications. Empty idea
descriptions use title-only text matching with a warning; out-of-vocabulary
queries and empty candidate text produce explicit zero similarity. Ties sort
by name, source and record IDs; scores round to six decimals.

Default comparison bounds: 5,000 input records, 2 million text-plus-serialized-field
characters, 20,000 characters per record, 30,000 vocabulary features, 20 selected
ideas, and top 10 results per idea. Limits fail with a filtering/splitting message;
inputs are never silently truncated. Sparse matrices avoid all-pairs document
comparisons, and heavy numerical libraries load only when comparison begins.
No embeddings installation is required. Optional semantic embeddings are deferred.
The tests use synthetic fixtures; there are no labeled real supervisor judgments,
so no Precision@K, Recall@K or NDCG accuracy claims are made.

## Configuration and limits

`config.toml` is loaded relative to the application directory. `[import]`
configures input bytes (default 20 MiB), expanded archive bytes (100 MiB), ZIP
members (5,000), records (20,000), extracted text/field characters (10 million),
PDF pages (500), and minimum page text (10 characters). Limits must be positive
integers. Imports use bounded input snapshots and lazy parser imports. They do
not stream indefinitely; parser CPU and peak memory are not hard sandboxed.
Keep limits modest on an 8 GB Mac and import only documents you trust enough to
process locally. XLSX/DOCX archive limits are checked before parsing.

## Security and authorization

Read [SECURITY.md](SECURITY.md). Local import never executes macros, scripts or
shell commands. Macro-bearing Office files are rejected. Encrypted or restricted
PDFs require an authorized export. No OCR or restriction workaround is provided.
Authentication alone does not authorize bulk extraction. Obtain permission and
an owner-provided export where access is restricted.

No import data, embeddings, credentials or document contents are sent to remote
services. Menu imports write only to the configured output directory. The standalone
importer still performs no writes. Output files reject traversal and path
escapes. Exports use exclusive creation and atomic publication.

## Verification

```zsh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python spiderdeck.py --security-check
bash -n install.sh
python -m pip_audit --local
```

Tests generate all supported document formats in temporary directories and run
offline. The security self-check has 11 in-process cases; it is a smoke test,
not proof of network security. The dependency audit needs network access.

## Troubleshooting and limitations

For unreadable/corrupt documents, verify permissions and obtain a valid original
export. Text inputs must be UTF-8. For scanned or low-text PDFs, request an
authorized text-based export; no text is silently fabricated. Cached XLSX formula
values may be absent or stale. DOCX headers, footers, text boxes and nested tables
are not imported. HTML is not rendered and Markdown is retained as source text.
Parser resource limits cannot guarantee a fixed peak memory usage or CPU time.

Next: authorized static web collection with transport-level destination policy,
explicit target approval, robots/rate limits and offline network tests. No network
collection is enabled by the current menu.

The PDF stack is pinned to `pdfplumber==0.11.10` and
`pdfminer.six==20260107`, addressing the two Phase A audit findings. Importing
PDFs with an outdated parser is refused. See [SECURITY.md](SECURITY.md) for the
advisories, verification results and remaining boundaries.

## Phase B verification snapshot

On the development Python 3.13 environment, the complete suite passed **90 tests**,
the security self-check passed all **11 cases**, dependency imports and `pip check`
passed, and the final installed-package audit reported no known vulnerabilities.
Tests include offline import → persistence → reopen → filtered search → export,
transaction rollback, duplicate/collision handling, Unicode, unsupported schemas,
unsafe filesystem targets, failed export cleanup and menu workflows.

A generated 5,000-row CSV measured 0.040 s import, 0.638 s transactional save,
0.005 s keyword count and 0.672 s streamed JSON export. Save/search/export peaked
at 0.79 MiB incremental Python allocations under `tracemalloc`, excluding the
already imported records and native SQLite/parser allocations. This is a small
synthetic development baseline, not an upper bound or large-database benchmark.


## Phase C verification snapshot

The complete suite passes **142 tests**, including all Phase A/B behavior,
version 1 → 2 migration preservation and rollback, idea lifecycle and validation,
toy expected ordering, missing information, zero similarity, duplicate grouping,
Sinhala/Tamil text, reproducibility, configurable weights, bounded workloads,
menu integration, offline end-to-end comparison and no-overwrite JSON export.
The 11-case security self-check, dependency imports and `pip check` pass; the
installed-environment dependency audit reports no known vulnerabilities. No new
runtime dependency was added. Optional semantic embeddings remain unimplemented.

A synthetic comparison of 1,000 candidates against four ideas took 0.232 s warm.
A separate cold measurement under `tracemalloc` took 4.423 s and peaked at 71.9 MiB
of Python allocations including lazy numerical-library imports. Imported input
records were allocated before tracing; native allocations and total process RSS
are excluded. This is a development baseline, not a hard resource bound or an
accuracy evaluation.
