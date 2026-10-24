# SpiderDeck

Local-first research document intelligence for Python 3.13 (tested on macOS).
SpiderDeck imports authorized local documents without network requests or remote AI.
Website collection, persistence, search, exports and ranking are not implemented yet.

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
Imported 12 records; 12 records in this session.
Session data is held in memory only and will be lost on exit.
```

Inputs may be outside `output/`. Folder recursion is not supported. Imports
are atomic: a failed import returns no partial records. Documents are not
printed or logged. Results accumulate in memory during the menu session;
there is no browse/export command yet. The reusable API is:

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
Cross-source content deduplication belongs to the next storage phase.
Timestamps serialize as ISO 8601 UTC with a `Z` suffix.

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
services. No generated files are written during import. Output path validation
rejects traversal, absolute paths and resolved symlink escapes; future writers
must additionally enforce exclusive creation and defend against path races.

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

Next: transactional SQLite storage with schema versioning, reimport/content
hashing, search and safe CSV/JSON exports. After that, implement configurable
research ideas and explainable offline TF-IDF supervisor ranking. Ranking is
not currently available, and no suitability or evaluation claims are made.

The Phase A dependency audit found two known vulnerabilities in the installed
PDF dependency (`pdfminer-six==20231228`). See [SECURITY.md](SECURITY.md) before
processing untrusted PDFs; upgrading the PDF stack is a priority follow-up.
