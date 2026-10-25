# SpiderDeck

Local-first research document intelligence for Python 3.13 (tested on macOS).
SpiderDeck imports authorized local documents without network requests or remote AI.
Imports persist in SQLite and support browsing, search and CSV/JSON exports.
Research ideas and explainable offline supervisor ranking are available.
Authorized static HTML and public JSON API collection is available after explicit
per-run target approval. Browser rendering and authenticated sessions are not available.

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

Settings are **read-only**: edit the TOML file and restart to change persisted
configuration. `--config` input paths are relative to the shell's current directory
when not absolute. Relative output paths still resolve against the application
directory. `--show-settings` prints configuration values and defaults (not runtime
TTY/display preferences), escapes controls in JSON, and does not create/open a
database. Invalid/missing configuration returns code 2 with a sanitized message
without printing private TOML source snippets.

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

- **1) Authorized static web collection** requires an exact hostname allowlist and explicit per-run approval.
- **2) Import** commits the complete document in one transaction.
- **3) Browse** previews 20 records at a time.
- **4) Search** combines keyword, source-path substring and exact document-type filters.
- **5) Research ideas and supervisor ranking** manages saved ideas and compares them locally.
- **6) Security audit and collection logs** runs the self-check or inspects recent private audit summaries.
- **7) Settings** shows configuration and paths without opening the database.
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

## Authorized static web collection

This increment supports public HTML/XHTML and explicitly authorized **public JSON
GET endpoints**. It does not log in, use credentials/cookies, submit forms,
execute JavaScript, fetch assets/iframes, follow refresh tags or run a browser.
Authentication alone is not permission for bulk extraction. Obtain appropriate
permission before collecting anything.

1. Add an **exact hostname** to `[crawl].allowed_domains` in `config.toml`, e.g.
   `allowed_domains = ["research.example.org"]`. No wildcard/subdomain inheritance
   or numeric IP targets are accepted.
2. Choose **1) Authorized static web collection** and enter the URL.
3. Review the scheme/hostname scope and page/depth limits, then explicitly confirm
   permission for automated GET requests on that origin. A configured domain alone
   does not grant approval. Declining makes no DNS, HTTP or database requests.
4. Accepted pages become `web_html` or `web_json` records in the existing SQLite
   database. Use browse/search/ranking/export normally afterward.

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

Next: expanded adversarial testing and security review (Phase G). JavaScript
rendering, authenticated sessions and broader API support remain deferred until
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
