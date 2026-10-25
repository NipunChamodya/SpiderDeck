# SpiderDeck

Local-first research document intelligence for Python 3.13 (tested on macOS).
SpiderDeck imports authorized local documents without network requests or remote AI.
Imports persist in SQLite and support browsing, search and CSV/JSON exports.
Research ideas and explainable offline supervisor ranking are available.
Authorized static HTML and public JSON API collection is available after explicit
per-run target approval. Browser rendering and authenticated sessions are not available.

## Research projects — start here

Launch `python spiderdeck.py`, choose **0) Research projects and focused collection**,
then **Create project**. Existing shortcuts remain: **1** Quick Crawl, **2** local
import, **5** supervisor ranking, **8** exit and **9** legacy CSV/JSON export.

1. Enter a research title, optional description, reviewed comma-separated keywords
   and excluded topics. Literal title-token suggestions are editable and are not
   inferred scientific facts. Select **Balanced**, **Strict** or **Discovery** and
   confirm creation. Projects stay entirely local.
2. In the dashboard choose **Collect authorized websites**. Each starting URL has
   its own exact-host approval, audited access check and separate start confirmation.
   Add another seed interactively afterward; no new domain is authorized by relevance.
   Each seed is a separate bounded run, not an unattended multi-domain crawl.
3. Or choose **Import documents** and select a file in the native macOS picker.
   Relevant records and bounded-scoring review candidates are linked to this project;
   low-relevance records are skipped and reported. Quick import remains unfiltered.
4. **Browse evidence** or **Search project** opens readable documents with source,
   location, timestamps, score components/matches/missing terms, quality notices,
   paginated cleaned text and optional original extracted text. No generated summary
   or peer-review claim is invented. Set a source category only with a user evidence note.
5. **Export findings** writes Markdown, structured JSON or predictable-column CSV.
   Optional keyword/source/type/date filters select the export. A filename without
   an extension prompts for format. Existing private exports need explicit replacement
   consent and a private backup; unsafe files are never replaced.
6. **Edit research settings** changes title, description, terms, exclusions, mode,
   thresholds or search mode. Existing assessments remain labeled as earlier settings
   until **Reassess stored evidence** is explicitly chosen. Reassessment preserves
   all linked/raw evidence, including records that are now low relevance.
7. Archive/unarchive projects or permanently delete a project with `DELETE` plus a
   second confirmation. Deletion removes only project metadata/associations and
   unreferenced assessment profiles. Shared records, source documents, history and
   exports remain; this is not secure erasure.

### Topic scoring, modes and coverage

Matching is deterministic lexical processing over NFC Unicode with Sinhala/Tamil
combining marks and script joiners preserved. No translation, embeddings, model
or API download is required. Reviewed keywords (or literal title suggestions) are
primary concepts; the description contributes to the cosine component. Phrase
matching respects Unicode token boundaries.

The score is `100 × (0.15 title coverage + 0.10 heading coverage + 0.45 body concept
coverage + 0.20 body phrase coverage + 0.10 token-count cosine) − exclusion penalty`,
clamped to 0–100. Each exclusion match subtracts 25 points, capped at 50.
Single-token concepts supply phrase coverage when no multi-token concepts exist.
The overlapping coverage/phrase weights total 0.65 deliberately; they are correlated
signals, not independent evidence. Scores are normalized **heuristics, not
probabilities, verified source quality or proof of supervisor suitability**.

- **Strict**, default threshold 60: relevant seeds and promising links only; use an
  on-topic starting page rather than an unrelated homepage.
- **Balanced**, threshold 35: prioritizes promising links and allows one consecutive
  low-relevance navigation hop.
- **Discovery**, threshold 20: allows two such hops and more adjacent exploration.

Thresholds are per project and configurable, with Strict ≥ Balanced ≥ Discovery.
Link priority is 45% anchor relevance, 35% URL-path relevance, 10% neighboring
paragraph/list context and 10% parent relevance. URL terms only influence traversal,
never establish a page's relevance or authorize its hostname. A heap orders by
priority, depth and canonical URL; per-run URL dedup/frontier/page/depth limits stay
in effect. Relevance cannot change robots, TLS, DNS/IP or redirect rules.

At most 200,000 text characters per record are scored by default (configurable
1,000–2,000,000). Larger records are explicitly marked **review**, not confidently
classified; they remain linked for inspection. Coverage counts stored matched
concepts: 0 Missing, 1 Limited, 2–4 Moderate, 5+ Strong. These labels count records,
including exact copies, and do not establish independent evidence or comprehensive
research coverage. Stale assessments are identified after edits.

The authored synthetic judgments in `tests/fixtures/research_judgments.json`
require explicit phishing detection plus WebAssembly implementation. Evaluation
is reproducible through the research benchmark; it is not external real-world
research ground truth. Precision/recall/NDCG results belong only to that fixture.

### Structured evidence and incremental collection

Original extracted text, fields and location metadata are retained. HTML main
regions, headings, paragraphs, lists, tables, links and source-declared author,
publisher/date are available when present. Multiple articles are not reduced to
just the first. Normalization uses NFC, canonical line breaks, trailing/outer
whitespace and excess blank-line normalization; internal mathematical whitespace
is preserved. Exact duplicate paragraphs are counted, not deleted. Main-region
selection is recorded as a transformation, not applied to the original text.
Structural previews have independent count/500,000-character budgets; full
extracted text remains available. Link discovery caps individual URLs at 4,096
characters, 10,000 candidates and 2 million URL characters per page, or lower
configured bounds. No raw HTML or original binary file is copied into SQLite.

PDF page references, DOCX paragraphs/headings, spreadsheet rows/headers and JSON
pointers retain provenance. Replacement/unmapped PDF glyphs generate warnings;
absence of a warning is not proof of text accuracy. No automatic OCR is used.
Source-declared metadata is unverified; source category defaults to unknown.

Project collection saves safe ETag/Last-Modified validators referencing complete
persisted pages. Recollection still gets robots and performs all destination,
TLS, authorization and limit checks; only then may a legitimate 304 reuse evidence.
Cached content is rescored for the current project. Cookies/authentication headers
are never cached or sent. Cached nofollow rules and new response robots restrictions
remain enforced. Pages with only partially retained JSON records and low-relevance
pages are not conditionally cached. Quick Crawl keeps its previous uncached behavior.

Summary definitions: pages visited are fetched page responses, relevant/low/review
are scoring outcomes, unchanged counts 304 reuse (a subset of those outcomes),
failed pages are terminal page failures, and new versions are new content at an
existing source/type/location. Counts are not all mutually exclusive. Collection
history records each seed or document import, with fixed statuses and count-only
summaries; it contains no cookies, tokens or page bodies.

### Schema 3 and migration safety

Existing schema-1/2 databases get a private `migration-vN-<uuid>.sqlite3` backup
inside output before a transactional additive migration. Backup integrity and
record/import counts are verified. Failure rolls back DDL/version; no database is
silently recreated. Existing records, IDs, timestamps, manifests, supervisor ideas
and historical duplicates are unchanged. Older code will refuse schema 3; use the
new application or restore a trusted pre-upgrade copy while SpiderDeck is stopped.

New tables: `projects`, `project_records`, `research_profiles`, `research_details`,
`research_sources`, `collection_runs`, `http_cache`, `record_copies`, and
`research_fts_map`; optional `research_fts` uses FTS5. Associations share records;
assessment profiles are SHA-256-addressed and stored once. New exact payload copies
reference a retained canonical record after full equality checks, while keeping
their own source/title/location/time. Different content remains a new version.
Legacy duplicates are not rewritten/compacted. Derived structures may still repeat
per source. Near-duplicate detection is not implemented.

Use `RecordStore.search/iter_records` and project APIs to read effective content.
For new copies, raw SQL against `records.text/fields_json` sees placeholders; join
`record_copies.canonical_id` back to `records` to resolve payloads. No executable
view or trigger is added. Foreign keys, canonical-reference integrity, collision
checks and schema validation remain enforced. WAL/automatic VACUUM are deliberately
not enabled: the application is serial and no measured benefit justifies their
extra sidecars/write costs. Copies and indexes are local; backup/export data is
plaintext protected by ownership/0600 permissions, not database encryption.

Project searches default to the existing Unicode literal-substring behavior.
Filters include source/type and UTC last-association/check date, with stable
relevance/date/source ordering and page size 20. Optional per-project FTS mode uses
quoted token/phrase matching when runtime FTS5 exists, otherwise literal fallback;
it is not identical to substring search, particularly for multilingual text.
Contentless FTS uses a record mapping and does not keep another text copy. Exports
stream a read snapshot; JSON retains original text plus structured views and
assessment profiles, CSV neutralizes formulas, and Markdown fences untrusted
content and strips terminal/bidi controls while preserving script joiners.

See [MANUAL_TESTING.md](MANUAL_TESTING.md) for macOS acceptance/recovery steps and
[PERFORMANCE.md](PERFORMANCE.md) for measured results and reproducible commands.

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
`--setup` is not an available command. Startup is static by default.
`--animate` explicitly enables startup effects after security checks on a capable
terminal, if `[fx].enabled` permits them. `--no-fx` remains supported as an alias
for `--no-animation`; it also selects static progress messages.

## Terminal modes, progress and settings

```zsh
python spiderdeck.py                              # arrow keys on a capable terminal
python spiderdeck.py --plain                      # numbered prompts; no cursor-based progress
python spiderdeck.py --quiet --reduced-motion     # retain results, errors and approval prompts
python spiderdeck.py --no-animation               # legacy --no-fx also works
python spiderdeck.py --animate                    # optional startup effects, after checks
python spiderdeck.py --config /path/to/local.toml # explicitly chosen configuration input
python spiderdeck.py --show-settings              # defaults plus TOML values as JSON
python spiderdeck.py --security-check --quiet     # concise actual PASS/FAIL result
```

The startup security check runs before banners or cosmetic effects. Passing is
shown as a short notice; detailed checks remain available in menu **6)** or with
`--security-check`. Failing cases remain visible in quiet mode, and web collection
stays disabled after a failed startup check. `--quiet` hides optional notices and
progress, not results, errors, ranking uncertainty, consent prompts or safety
messages. It is not a JSON-only automation interface and never means “approve”.

Arrow-key/questionary navigation is preserved on interactive terminals. Piped
input/output, `TERM=dumb`, `NO_COLOR`, or `--plain` use numbered prompts. Main
menu numbers retain their existing meanings: **8 quits, 9 exports**; `q` also
quits in plain mode. Other menus use the numbers shown, and plain multi-selection
accepts comma-separated numbers. Empty/EOF confirmation means **no**. Blank text
is an intentional answer (e.g. keep a field during editing), while EOF/Ctrl+C
cancels a text form before saving incomplete edits. EOF at the main menu exits.
Ctrl+C during actual work returns exit code 130; previously committed data stays
saved, and an interrupted SQLite transaction is rolled back. Collection handles
its own cancellation and can retain earlier accepted pages as documented above.

`--reduced-motion`, `--no-animation`, `SPIDERDECK_REDUCED_MOTION=1`, quiet/plain
mode and noninteractive terminals suppress cosmetic motion. Reduced-motion mode
keeps interactive arrow navigation where supported but uses static status text.
`--animate` cannot be combined with `--no-animation`/`--no-fx`; other motion
suppression settings override an animation opt-in. No new rendering thread or
background worker was added.

Import/extraction, saving, search and ranking show their current phase. Collection
reports accepted-page counts while preserving its existing rate limits; exports
show processed records and a count taken at export start. Unknown totals are not
presented as percentages. [Rich progress](https://rich.readthedocs.io/en/stable/progress.html)
is refreshed manually on work updates (refreshes throttled to at most 10/second), with
`auto_refresh=False`; it adds no spinner thread or cosmetic sleep. Reduced-motion
and redirected output print one static stage notice instead. Display I/O errors
disable progress rendering rather than interrupting data processing. Another
process changing the database can make an export's initial count differ from
its final record count.

Settings retain a read-only summary and add confirmed interactive actions for
exact hostname approvals and crawl limits. Changes are atomic, keep private
backups beside the selected TOML file, and preserve unrelated settings/comments
where safely editable. Stale dialogs and concurrent SpiderDeck writers are
refused; reload saved crawl settings and review the change again. Unusual TOML
layouts are refused rather than rewritten wholesale. No database opens for
settings. `--config` selects the file edited by these actions; relative paths use
the shell working directory. Relative output paths still use the application
directory. `--show-settings` remains a read-only JSON command and creates no files.

Invalid configuration still returns code 2 in headless sessions. Interactive
Terminal sessions can explicitly enter safe session defaults with no approved
hostnames, then use **Settings → Recover unreadable configuration**. Recovery
requires another confirmation, preserves the original bytes in a private backup,
and resets configuration to documented defaults. Restart afterward; no database
is deleted or replaced. Missing/symlink/shared-writable configuration files cannot
be overwritten through these controls. Other non-crawl settings still require a
restart to take effect.

Menu **6)** can show up to 20 newest collection audit summaries without opening
SQLite. It only reads matching private regular files under output, refuses
symlinks/hardlinks, limits each JSON read to 64 KiB and displays validated origin,
outcome and aggregate counts. Raw events, document contents and URL paths are not
shown. Missing output is not created; oversized, malformed or unsafe files are
reported generically. This view is intentionally limited, not a full log editor.

Exit codes: 0 for normal exit/success; 1 for a failed explicit security check; 2
for invalid arguments/configuration; 130 for work interrupted by Ctrl+C; 141 for
a broken output pipe. Cancelling an individual prompt returns to its workflow/menu.
Tests cover both mocked interactive rendering and actual piped CLI sessions; a
full manual VoiceOver/terminal-emulator accessibility review has not been performed.

## Importing

Choose **2) Import a local document**. In a local macOS Terminal session, a
native Finder-style file-selection dialog opens. Select a supported document and
choose **Open**; cancelling the dialog returns without asking for a typed path.
NSOpenPanel is used if PyObjC is already installed, then tkinter is tried if
available, then macOS's built-in `choose file` dialog is invoked through a fixed
`osascript` argument list. No GUI dependency is installed. This repository's
Homebrew Python lacks `_tkinter`, so the built-in dialog fallback is relevant.
SSH/headless sessions and unavailable dialogs offer the existing text-path prompt.

```text
Filename: supervisors.xlsx
Document type: XLSX; file size: 12345 bytes.
Imported 12 records; saved 12 new records; skipped 0 duplicate identifiers.
Extracted characters: 2410.
Text preview (up to 300 characters): ...
Database: .../output/spiderdeck.sqlite3
```

Counts/sizes in this example are illustrative. The size comes from the validated
input snapshot. Preview text is short and strips terminal controls. The original
file is never launched in another application. After import, choose **Browse
imported records**, **Search imported content**, **Import another document**, or
**Return to main menu**. Browse/search stay scoped to that exact source path and
include earlier retained versions from that same file. Export remains in main
menu **9)**. Filenames with spaces, Sinhala and Tamil are supported.

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

- **1) Authorized static web collection** reviews and approves an exact hostname interactively, then requires per-run access-check and collection confirmations.
- **2) Import** commits the complete document in one transaction.
- **3) Browse** previews 20 records at a time.
- **4) Search** combines keyword, source-path substring and exact document-type filters.
- **5) Research ideas and supervisor ranking** manages saved ideas and compares them locally.
- **6) Security audit and collection logs** runs the self-check or inspects recent private audit summaries.
- **7) Settings** shows configuration and offers confirmed hostname/limit editing without opening the database.
- **9) Export** applies the same filters and asks for a new `.csv` or `.json` filename.
- **8) Quit** closes the application; saved records remain available next time.

Search is casefolded, NFC-normalized literal substring matching over record title
and text, with support for Sinhala, Tamil and English. `%`, `_` and SQL syntax
have no special meaning. All filters are combined with AND. Empty filters select
all records. Results sort deterministically by source, type and record ID.
Legacy all-record search uses the portable SQLite path, without FTS5; searches
scan candidate records and may slow down for very large databases.

Reimporting unchanged records skips their stable identifiers and preserves the
original extraction timestamps. A manifest of source and record IDs detects a
previously imported record set. Changed records are added; old versions are
retained. Equal content at another source/location is flagged, not discarded.
There is no automatic deletion, replacement, version comparison or byte-level
unchanged-file shortcut: local reimports still parse the input. Schema version 3
and an application ID identify current databases. Recognized schema-1/2 databases
receive the backed-up additive research migration described above. Unrelated files
and unknown versions are refused. Older code refuses the upgraded database.

Exports stream one record at a time, with no database-sized Python list. JSON
preserves the record schema, nested fields and Unicode. CSV uses a fixed column
schema with JSON in `fields` and `metadata`, quotes every cell and prefixes risky
spreadsheet cells with an apostrophe. CSV protection intentionally changes those
cells; JSON preserves exact content. Do not strip these prefixes before opening
CSV in a spreadsheet. Export only to a single filename directly under output;
subdirectories and absolute export paths are rejected. Legacy export names are
never overwritten; project exports add explicit backed-up replacement of private
regular files, never symlinks/hardlinks. Failed exports do not publish partial files.
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

## Authorized static web collection

This increment supports public HTML/XHTML and explicitly authorized **public JSON
GET endpoints**. It does not log in, use credentials/cookies, submit forms,
execute JavaScript, fetch assets/iframes, follow refresh tags or use a browser
for extraction. Optional default-browser opening is separate from collection.
Authentication alone is not permission for bulk extraction. Obtain appropriate
permission before collecting anything.

1. Choose **1) Authorized static web collection** and enter a complete HTTPS URL.
   URL/hostname validation is local and sends no requests. Ordinary query-free
   public HTTPS URLs need no manual configuration editing.
2. Review the hostname, page URL and page/depth/delay limits. For a new hostname,
   choose **Approve for this run only**, **Save hostname for future use**, or
   **Cancel**. Saving needs confirmation and a private configuration backup;
   entering the URL alone never grants approval. Exact hosts only: subdomains,
   different schemes and redirect destinations need their own approved workflow.
3. Explicitly authorize bounded automated access checks. Only then are DNS, IP,
   TLS, robots and seed-content checks performed with the existing pinned
   transport. A private audit is reserved first, without opening SQLite. The
   check reads robots.txt and one seed page, following only validated same-origin
   redirects; it does not follow discovered links. It uses at most 8 attempts,
   3 redirects per chain, 20 seconds of scheduled active work, 2 MiB per response
   and 4 MiB total, or stricter configured limits. OS DNS duration is not hard
   capped. Failed checks explain a safe next action.
4. If checks pass, optionally open the approved URL in the default browser.
   Browser cookies/sessions remain separate, and opening a page grants no
   collection access. Browser-launch failure does not prevent collection.
5. Separately confirm **Start collection**. The cached seed and robots result are
   reused; preflight requests, bytes and active time count against run limits.
   Human review time does not add network budget. Each later request resolves
   and validates again. Declining the final start saves no records from the
   access check; its aggregate audit remains under output.
6. Review pages, extracted/saved records, bounded discovered-link counts, skipped
   work, outcome, database location and audit name. Browse/search/export actions
   are offered for this origin, including earlier retained runs. A later blocked
   page can stop collection while previously accepted pages remain saved.

Saved hostnames still need per-run confirmation. Settings can add/remove them
without network requests. Invalid legacy allowlist entries (such as complete
URLs) remain preserved but inactive; they are never silently converted into
approvals. Remove an inactive entry through Settings when appropriate.


Approval is for one origin per run, not every host in the configured allowlist.
Same-origin links/HTTP redirects may be followed; external links are ignored.
Cross-origin redirects (including HTTP → HTTPS) stop and require a separate run
with explicit approval. Start directly at the HTTPS URL where possible. HTTP on
port 80 is supported with explicit approval but does not provide TLS confidentiality;
HTTPS on port 443 validates the original hostname and certificate chain. Other
ports, userinfo, query-bearing/signed URLs, ambiguous paths and IP-literal targets
are deliberately unsupported. Hostnames with public IPv6 DNS records are supported.
No proxy, environment proxy setting, authentication header or cookie jar is used.

Every HTTP request (including robots, retries and redirect hops) resolves all
addresses, rejects prohibited/mixed results, and connects to a selected approved
numeric IP without another DNS lookup. The TCP peer is checked. HTTPS retains the
hostname for SNI/certificate validation and the HTTP Host header. Retries may
select another address only after revalidating the complete DNS result set.
This is implemented with Python's [HTTP client](https://docs.python.org/3.13/library/http.client.html)
and a verifying [TLS context](https://docs.python.org/3.13/library/ssl.html).
The legacy `validate_url` helper is not the live network enforcement boundary.

The crawl is sequential. Robots rules are fetched through the same transport
before pages, then enforced on every page and redirect destination. The parser
supports merged matching User-Agent groups, longest-match rules, Allow ties,
`*`/`$` paths, Crawl-delay and Request-rate. A robots 404 permits crawling; access
failures, unavailable robots, invalid rate directives and unsupported responses fail closed.
Unknown directives/unparseable lines are ignored; an empty rule file permits paths.
Path matching follows [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html)
matching concepts; this collector deliberately narrows allowed URL and redirect scope.
The larger of the configured delay and robots delay is used. Transient transport
failures and 502/503/504 get bounded exponential retries; Retry-After is respected
or collection stops if the requested wait exceeds the run budget. Permission
failures and 429 stop without retrying. Robots is a technical signal, not legal
or organizational authorization.

Defaults: 50 pages, depth 2, 1.5 seconds between requests, one concurrent request,
10 seconds per request, two retries, three redirects per chain, 200 transport
attempts, 1,000 scheduled URLs, 2 MiB per response, 10 MiB accepted response bodies,
10,000 records and a 120-second scheduling budget. Robots and retries count toward
request/byte budgets. Response headers/chunk framing have a 64 KiB cumulative
line budget. Compressed responses are refused; clients request identity encoding.
The active socket is closed by a bounded request-deadline watchdog; the watchdog
is cancelled/joined after each request. There are no persistent worker processes.
OS DNS lookup itself cannot be interrupted reliably, so this is not a hard wall
clock/CPU/RAM sandbox. There is no crawl throughput benchmark against live targets.

Collection stops on access restrictions, CAPTCHA/login indicators, export-disabled
content, Google Docs/Sheets viewer URLs or insufficient static text. It suggests
an authorized export or officially supported API instead. Restriction heuristics
are conservative and can reject legitimate pages discussing these terms. The
collector never performs OCR, accessibility scraping or bypasses access gates.
JSON endpoints preserve structured items and JSON pointers; malformed/nonfinite
JSON and unexpected content types are rejected. Text encoding is limited to UTF-8,
ASCII, ISO-8859-1 and Windows-1252; plain text is accepted only for robots.txt.

Each run publishes a new private `crawl-audit-<id>.json` under output. It records
origin, fixed event/outcome codes, timestamps and aggregate collection/storage
counts. It excludes paths, query strings, bodies, response headers, credentials
and exception details. Audit file access is checked before network activity.
An abrupt process/OS failure or output-disk failure can prevent final audit
publication; the UI reports an unavailable audit rather than claiming success.
Previously accepted pages can be retained when a later page stops the run. Each
page is stored transactionally; a storage failure can leave earlier pages saved
and is recorded as `storage_failed`. Existing records/files are never replaced.

All collection tests run offline with mocked DNS and socket wire fixtures. They
exercise real HTTP parsing/serialization and storage integration, but do not
claim a real TLS handshake, real remote server interoperability or live-site
permission. No university website or other live target was contacted in testing.

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
PDF pages (500), minimum page text (10 characters), XML nesting depth (100),
and spreadsheet columns (1,024). Limits must be positive
integers. Imports use bounded input snapshots and lazy parser imports. They do
not stream indefinitely; parser CPU and peak memory are not hard sandboxed.
Keep limits modest on an 8 GB Mac and import only documents you trust enough to
process locally. XLSX/DOCX archives receive a streaming XML preflight before the
Office libraries run. DTDs/entities, unsafe ZIP member paths, symlinks, duplicate
members, malformed XML and excessive nesting are refused. Worksheet dimensions,
actual cell coordinates and row counts are checked, including unused/blank rows.
Trim inflated worksheet ranges or split large sheets; increase
`max_spreadsheet_columns` explicitly if a legitimate wide sheet requires it.

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
without external websites. Real TLS integration tests bind an ephemeral HTTPS
server to `127.0.0.1`; restricted test environments must permit local listeners.
Tests generate private temporary CA/leaf keys and validate certificates using
OpenSSL. Test-only routing maps the approved fixture endpoint to that listener;
production continues to reject loopback and nonstandard ports. You can run these
separately with `python -m pytest tests/test_tls_integration.py -q`.
The security self-check has 23 in-process cases and needs no network or files;
it is a smoke test, not proof of network security. The dependency audit queries
package names/versions and needs network access; it sends no imported documents.

## Troubleshooting and limitations

For unreadable/corrupt documents, verify permissions and obtain a valid original
export. Text inputs must be UTF-8. For scanned or low-text PDFs, request an
authorized text-based export; no text is silently fabricated. Cached XLSX formula
values may be absent or stale. DOCX headers, footers, text boxes and nested tables
are not imported. HTML is not rendered and Markdown is retained as source text.
Parser resource limits cannot guarantee a fixed peak memory usage or CPU time.

Security regression coverage includes Phase G TLS, diagnostic privacy and hostile
document tests. JavaScript rendering, authenticated sessions and broader API
support remain deferred until
equivalent transport-level network policy can be enforced.

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


## Phase D static-collection verification snapshot

The complete suite passes **262 tests**, including all Phase A/B/C behavior and
120 additional offline collection/security cases. The 11-case security self-check,
installed dependency imports, `pip check`, installer shell syntax and diff checks
pass. The installed-package dependency audit reports no known vulnerabilities.
No new runtime dependency was introduced and no live collection was performed.

Unit tests cover authorization before DNS, URL/IP bypasses, mixed DNS results,
IPv6 translation ranges, DNS changes, direct-IP dialing, peer verification,
TLS context requirements/failures, request deadlines, header/body bounds,
robots matching/rates, redirects, retries, restriction detection and audit privacy.
Offline integration uses mocked socket wire responses with actual HTTP parsing,
SQLite persistence and search, plus menu/audit workflows. Manual code review
addressed SSLKEYLOGFILE writes, retry-after delays, HTML base links and empty
script-only pages. This is not a live HTTPS interoperability test or an external
penetration test. Authenticated/browser collection and unrestricted API URLs
remain deliberately unavailable.


## Phase E verification snapshot

The full suite passes **313 tests**, preserving all 262 earlier cases and adding
51 CLI/presentation/cancellation cases. The 11-case security self-check, installed
imports, `pip check`, installer shell syntax and diff checks pass. The final
installed-package dependency audit reports no known vulnerabilities. No new
runtime dependency or database schema change was introduced.

Coverage includes startup security-before-effects ordering, display overrides,
quiet failures, actual piped import/search/export sessions, EOF at target approval,
cancelled idea forms, read-only settings/audit inspection, unsafe audit files and
progress renderer failures. A manual PTY smoke test verified arrow-key selection
and clean Ctrl+C exit; a full terminal-emulator/VoiceOver review remains pending.

Three fresh-process `--plain --quiet` runs including interpreter startup, security
checks and immediate exit took 0.229, 0.134 and 0.138 seconds on the development
environment. These are small startup samples with filesystem caches in effect,
not idle CPU measurements or a comprehensive Phase F performance assessment.


## Phase F: performance and reliability

Run the opt-in offline synthetic benchmark with:

```zsh
python -m benchmarks.run --rows 5000 --repeats 3
```

Reports are private files under a new directory in configured output. The tool
never reads user documents or the existing application database and cleans only
its own synthetic workspaces by default. Memory/profiling modes, methodology,
observed before/after results and limitations are in [PERFORMANCE.md](PERFORMANCE.md).

Measured warm ranking improved from 0.267 s to 0.050 s and storage-only reimport
from 0.118 s to 0.049 s on the documented fixtures. CSV Python allocation peak fell
from about 20.0 MiB to 7.5 MiB. Input reads reject concurrent changes and no longer
preallocate the full configured maximum for every small file. CSV decoding is
incremental over the existing bounded snapshot. PDF page limits are enforced
before constructing later page wrappers; permission checks and no-OCR behavior
remain intact. Public record serialization, ranking outputs, SQL transactions,
security controls and schema version 2 are preserved. No runtime dependency or
application concurrency was added.


Phase F verification: **334 tests pass**, including the unchanged ranking output
snapshot, file-change/FIFO/symlink races, lazy PDF limits and cleanup, nested-record
persistence, all benchmark modes/workloads and honest failure reporting. The
11-case self-check, imports, `pip check`, installer syntax and diff checks pass;
the installed-package dependency audit reports no known vulnerabilities. A
20,000-row synthetic pipeline run also completed. Hard parser CPU/RAM isolation,
real-world relevance evaluation and live-network performance remain outside these
measurements.

## Phase G security hardening

Real local HTTPS integration tests cover valid, expired and untrusted certificates,
hostname mismatch, handshake timeout, socket cancellation, and a keyboard
interrupt during a blocked handshake. Offline adversarial fixtures cover corrupt
PDFs and Office archives, DTD/entity attacks (including UTF-16), ZIP traversal,
symlinks/duplicates, encryption flags, CRC errors, archive expansion, excessive
XML nesting and malicious spreadsheet dimensions/cell references.

Known parser logger namespaces and warnings are contained during local and web
parsing, with a generic notice when diagnostics are omitted. Raw document text,
tokens, cookies, passwords and sensitive query URLs are tested against captured
logs/output. Public parser and transport exceptions suppress document-derived
chained tracebacks. HTTP header debug printing is disabled; audit error/event
codes use a finite allowlist. The unused legacy logging helper no longer creates
`logs/` files or records raw source strings. Collection audit files remain under
the configured output directory.

The parser diagnostic guard supports the application's serial parsing workflow;
it temporarily changes dependency logger handlers and process-wide warning hooks.
Concurrent external reconfiguration of those hooks is unsupported. Imported
records, explicit browsing and user-requested exports still contain the data you
chose to collect; they are not diagnostic logs and are not automatically redacted.
See [SECURITY.md](SECURITY.md) for verification scope and remaining limitations.

Verified on 2026-10-25 with Python 3.13.4: **419 tests passed in 8.55 seconds**,
all 23 self-check cases passed, dependency imports and `pip check` passed, and
`pip-audit --local` reported no known vulnerabilities. The full suite included
all 7 real local TLS cases; none were skipped. No runtime dependencies or database
schema changes were introduced by this Phase G increment.

## V1 manual acceptance checks

See [MANUAL_TESTING.md](MANUAL_TESTING.md) for beginner macOS checks of native
selection, previews, interactive approvals, settings, recovery and exports.
Native dialog and browser interactions are mocked automatically; no visual macOS
acceptance test or live-site collection is claimed as performed. No new runtime
dependency or database schema change was introduced for these V1 workflows.

V1 verification on 2026-10-25 (Python 3.13.4): **485 tests passed in 8.18 seconds**,
including 65 focused configuration/workflow tests and all 8 real loopback HTTPS
integration cases. All 23 security self-check cases, dependency imports,
`pip check`, installer shell syntax and diff checks passed. `pip-audit --local`
reported no known vulnerabilities. Native Finder-panel appearance/focus and
browser handoff remain NOT RUN manually; use the manual-testing guide.


Research-engine known limitations: topic matching is lexical (including false
positives/negatives), not semantic understanding. Source classification and
publication metadata are not verified. Source metadata-only changes may not create
a new content identity; original extraction metadata is retained. Near-duplicate
merging, generated summaries, embeddings, browser/authenticated collection,
automatic database compaction and Windows support are not implemented. Collection
is sequential per explicitly approved seed; exports contain all linked records
unless explicitly filtered, including retained review/low-relevance evidence.
Native macOS visual acceptance remains documented rather than claimed complete.
