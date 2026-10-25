# Security model and current boundaries

The application imports explicitly selected local files and collects approved
public static HTML/JSON endpoints. It does not render browser content, fetch
subresources, execute macros or run document-supplied commands. No remote AI services are used. Import failures
return sanitized messages without document contents. Existing logs are preserved;
the import menu does not activate the legacy file logger.

Input snapshots, extracted record/text limits, ZIP expansion/member checks and
PDF page limits bound common resource usage. These are not a parser sandbox or
hard CPU/RAM limits. Third-party parser vulnerabilities remain possible; keep
libraries audited and process adversarial files in an isolated environment.
No archive entries are extracted to disk. PDF extraction restrictions are checked;
request an authorized export instead of circumventing them. Macro-bearing Office
archives are rejected. Local files are assumed to have been obtained with permission;
SpiderDeck cannot infer organizational permissions from a local file.

The output validator uses path component containment rather than a string
prefix. Phase B adds directory-descriptor-based export creation with no-follow,
exclusive temporary files, and atomic create-if-absent publication. A failed
export does not publish a partial final file; preexisting files and symlinks
are never replaced. Generated files have mode 0600. Local inputs may legitimately
reside outside the output directory.

SQLite opens pathnames through its own native transport. The repository checks
that output is owned by the current user and not writable by group/others. It
rejects symlink/hardlink/nonregular database and sidecar files and requires their
permissions to be private. It checks the directory identity and uses a fixed
filename. These checks rely on trusted directory ancestors and exclude hostile
processes running as the same OS user; Python preflight cannot eliminate every
SQLite pathname race. They are not a filesystem sandbox. Do not place output in
shared-writable directories or replace it during an operation. No permissions
are silently relaxed or changed on existing data.

SQLite uses parameterized data statements, bounded lock waits, transactional
schema initialization and document writes, an application ID and schema version.
Unknown versions, unrelated files/databases and executable schema objects are
refused. No arbitrary database import is offered. Extension loading is not
activated; trusted schema is disabled. SQLite temporary storage is configured
in memory, with a 2 MiB page cache target. Journal files remain in output.
Records are never automatically deleted or overwritten. ID collisions with
unequal stored values roll back the whole import.

The database and exports contain document contents and source paths in plaintext.
Use macOS account permissions/FileVault or another appropriate disk protection
method if needed. CSV formula defenses prefix dangerous cells (including leading
whitespace formulas) and quote every cell; downstream modifications or spreadsheet
re-saving can remove protection. JSON is a lossless data export, not a script.
Browse/search strips terminal controls from untrusted previews. Import/save errors
do not write document contents to logs. Existing legacy logs are preserved.

## Phase D: static network boundary

Live HTTP collection uses `security/network_policy.py` and
`crawler/fetcher.py`, not the legacy preflight URL helper. Each run requires a
explicitly approved exact hostname (run-only or saved) and a declaration of automated-collection
permission for one origin. No target is automatically authorized because another
host, subdomain, port or scheme was approved. Discovered external links are
ignored; redirects outside the approved origin stop. Browser rendering and
session/authenticated APIs remain unavailable; interception alone would not
provide an equivalent destination-IP guarantee.

All DNS answers are validated before choosing a destination. Non-global,
private, link-local, loopback, multicast, reserved, scoped, IPv4-mapped, 6to4,
Teredo and non-2000::/3 IPv6 results (including common translation ranges) are
refused. Mixed safe/unsafe DNS sets fail closed. Hostname-only URLs exclude IP
literals and alternative numeric representations. Numeric socket connect on
an explicit address family prevents a hostname re-resolution at connect time.
The actual peer must match the selected address. Every retry and redirect
resolves and checks again. Connection reuse, proxies, browser requests and
unvalidated fallback transports are not enabled.

HTTPS validates the original hostname/certificate chain with a verifying client
context, TLS >= 1.2 and HTTP/1.1 ALPN. HTTP Host remains the approved hostname;
the IP is only used for dialing. SSLKEYLOGFILE is deliberately not honored, so
normal use cannot create an external TLS secret log. Query URLs, userinfo,
ambiguous encodings/path traversal, nonstandard ports and interactive Google
Docs/Sheets viewer routes are unsupported. No tokens, cookies or authentication
headers are collected or reused. Plain HTTP is available only when that origin
is approved and provides no confidentiality; prefer HTTPS.

The policy assumes trusted OS routing, DNS infrastructure and TLS trust store.
It cannot prevent a hostile VPN/NAT/router from remapping a public destination
or control what an authorized public server does internally. OS getaddrinfo
cannot be reliably interrupted by a Python socket deadline. The per-request
socket watchdog covers active TCP/TLS/header/body I/O, and scheduling/size limits
bound normal work, but there is no hard DNS, process CPU or RAM sandbox. Apply
an OS egress firewall/isolation if a stronger boundary is required. This is not
a blanket claim of browser or arbitrary-Python network security.

Robots is enforced before pages and on same-origin redirects; response metadata
robots restrictions are respected conservatively. Rate limits cover robots,
redirects and retries; blocked/unauthorized/rate-limited responses stop without
aggressive retries. No scripts/assets/iframes, form actions, browser APIs, OCR,
accessibility extraction, CAPTCHA solvers or credential/session workarounds are
used. Restriction detection can produce false positives; an owner export is
the supported fallback. A public response and an authenticated user are neither
proof of bulk-extraction permission.

Audit output contains only origin, fixed event codes/timestamps and aggregate
counts. Bodies, URL paths, queries, headers and exception strings are excluded.
A private exclusive audit temporary file is reserved before network work and
published atomically at completion; crashes/disk failures can prevent publication.
Accepted pages before a later failure may remain saved. A failed or restricted
page is never imported; earlier valid pages are not silently deleted. Storage
and audit remain local under output. Raw response headers/bodies only exist in
bounded memory during processing and are not debug-logged.

Verification combines offline DNS/socket fixtures with real loopback TLS
certificate integration tests (see Phase G and V1 below). Tests validate pinning,
rebinding, peer checks and certificate failures; they are not live-site penetration
tests or proof of complete SSRF security.

The current self-check is an offline 23-case smoke test, not a network security audit.
No dependency audit or test result implies complete security. Report dependency
findings and update dependencies in a separate reviewed change; do not silently
change existing user dependency choices.

## PDF dependency remediation and audit

Phase A's installed `pdfminer-six==20231228` produced `PYSEC-2026-1762` and
`PYSEC-2026-1761`. The maintainer advisories describe unsafe pickle loading in
CMap handling: a crafted PDF can select a malicious local pickle, and the
remaining loader behavior also permits local privilege escalation in affected
environments. The earlier patch was incomplete. Both current advisories list
`20251230` as the patched minimum:

- [GHSA-wf5f-4jwr-ppcp](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-wf5f-4jwr-ppcp)
- [GHSA-f83h-ghpp-7wcc](https://github.com/pdfminer/pdfminer.six/security/advisories/GHSA-f83h-ghpp-7wcc)

Requirements now pin `pdfplumber==0.11.10` and its compatible
`pdfminer.six==20260107`. The [pdfplumber changelog](https://github.com/jsvine/pdfplumber/blob/stable/CHANGELOG.md)
confirms that exact parser dependency. The resolver selected this pair without
other installed package upgrades. PDF importing refuses outdated or unrecognized
pdfminer versions. The updated pdfplumber exception wrapper is handled so corrupt
PDFs still return sanitized actionable errors. PDF permission enforcement remains
in place; no deserialization exploit or restriction bypass was executed as a test.

After installation, all original 38 tests and three new outdated-parser tests
passed; `pip check` passed and `pip-audit --local` returned no known vulnerabilities.
This audit outcome is limited to known advisories for the installed environment,
not proof that all parser behavior is safe. Audit again after dependency changes.
The runtime dependency list is pinned for direct requirements but is not a
complete transitive lockfile. Resource exhaustion and undiscovered parser flaws
remain possible; process adversarial documents with OS isolation.

## Phase C: research ideas and offline ranking

Schema version 2 adds an ideas table. Migration is allowed only from a recognized
version 1 schema with the expected application ID, table layout and no executable
schema objects. It creates one table and updates the schema version in a single
transaction. Existing records and import manifests are not rewritten or deleted;
a migration failure rolls back both DDL and version. Back up a stopped database
before upgrading; the old Phase B code refuses version 2. Ideas are validated and
saved with parameterized SQL. Removing an idea archives its content. Explicit
idea edits replace the chosen idea's fields; there is no edit-history workflow.

TF-IDF and weighted matching run entirely in process. There are no remote AI
providers, embedding downloads, browser sessions or automatic network calls.
Comparison input sizes, idea counts and sparse vocabulary sizes are bounded by
configuration; these limits are not hard process CPU/RAM isolation. Numerical
libraries load lazily. Results, saved ideas and optional JSON comparisons contain
plaintext research data and source paths under output; comparison previews strip
terminal controls and do not send document contents to logs.

Scores and detected identities are unverified heuristics. Duplicate grouping
preserves source record IDs but may combine namesakes when only names/source or
names/affiliation are available. Import history is additive, so contradictory old
versions can contribute to a comparison. Compare against appropriate source
filters and check the original records before drawing conclusions. Lexical
matching does not infer qualifications or consent, translate text, or prove
supervisor availability. No ground-truth evaluation data has been supplied.


## Phase E: presentation and cancellation

Display settings (`--quiet`, plain/reduced-motion modes and optional animations)
only control presentation. They do not skip security checks, relax target policy,
change file permissions or grant approvals. Startup checks run before cosmetics;
failing details are retained even in quiet mode. EOF/blank confirmation never
grants target approval, and cancelled text forms are distinct from submitted
blank values so incomplete idea edits are not inadvertently persisted.

Progress is manually refreshed without a rendering thread, timer or cosmetic
sleep. Only fixed stage labels and aggregate counts are used; document text,
URL paths and credentials are not passed to collection progress. Expected terminal
I/O/encoding errors disable progress rather than changing collection/storage
behavior. Operational exceptions still propagate to the relevant error boundary.
Existing network watchdog deadlines and rates remain unchanged.

Settings inspection is read-only and does not initialize/migrate SQLite. JSON
settings output escapes control/formatting characters; invalid config errors do
not echo TOML source. Explicitly chosen configuration inputs may be outside output.
Audit inspection uses an owned directory descriptor, no-follow private regular
files and bounded reads; symlinks/hardlinks, invalid formats and oversized logs
are ignored or rejected without printing their contents. Only validated summary
fields are shown. Startup, settings inspection and missing-audit inspection do
not create an output directory or database. No schema change or new runtime
dependency was introduced by this phase.


## Phase F: measured resource behavior

Local input descriptors now use no-follow/nonblocking opens with regular-file
and size checks after open. Explicit input symlinks resolve normally, but a final
symlink replacement is refused and a FIFO substitution cannot block the reader.
Snapshot size, mtime and ctime are checked after reading; changing files are
refused with a retry message. Only the checked input size plus a growth byte is
requested, avoiding a maximum-sized allocation for every small file.

CSV decoding is incremental over a bounded in-memory snapshot. PDF pages are
iterated lazily with per-page cleanup, after extraction permissions are checked.
Oversized page trees no longer eagerly construct every page wrapper during either
iteration or cleanup. PDF metadata/xref parsing and arbitrary document contents
still require parser resources: these changes do not create a CPU/RAM sandbox.

Ranking normalization is per-comparison and discarded afterward. Only top-K
sparse explanations are built, with compatibility tested against synthetic
pre-optimization results. No global document cache, embedding download or remote
provider was introduced. Persistence still compares every duplicate ID's stored
payload; it never trusts the identifier or import manifest alone to skip safety
checks, and the public deep-copy serialization interface remains intact.

The opt-in benchmark generates only synthetic fixtures in unique private output
workspaces, with no network or existing user data access. It uses serial child
interpreters for isolated measurements, not production parallelism. Cleanup is
limited to each workspace it just created and requires symlink-resistant removal;
reports are published exclusively. Failed/killed workers are not reported as
successful and may leave synthetic artifacts. `--keep-workloads` explicitly
retains fixtures. Reports do not establish real-world relevance accuracy or a
security guarantee. No data migration or security/network policy relaxation was
needed for the measured improvements.

## Phase G: initial increment (historical)

The first Phase G increment fixes two issues found by code review and reproduced
with offline tests. The TLS watchdog now owns the wrapped socket before an
explicit handshake begins. Previously, implicit handshaking could detach the raw
socket while the watchdog still referenced it. The handshake uses the remaining
request deadline; socket timeouts produce the fixed `request_timeout` error code
without exposing exception details. Certificate verification and hostname checks
remain enabled. Repeated leading slashes in Google document viewer paths now
trigger the same request-export stop as conventional viewer paths.

Regression coverage includes wrapped-socket registration, watchdog interruption
of a blocked simulated handshake, sanitized timeout errors, and repeated-slash
viewer paths. These are offline unit/component tests using controlled socket
fixtures, not live TLS integration tests or an external penetration test. They do
not establish operating-system routing isolation or bounded DNS resolver runtime.
At that checkpoint, real certificate-chain integration, parser diagnostic privacy
review and broader malicious-document coverage remained follow-up work. The
verification below supersedes that checkpoint.
Dependency audit results cover known advisories in installed Python packages;
they do not audit the interpreter, system OpenSSL, SQLite or unknown vulnerabilities.


## Phase G: TLS, parser privacy and malicious documents

The real TLS integration suite uses generated short-lived EC test CAs and leaf
certificates on a loopback-only HTTPS listener. It validates successful HTTPS,
expiry, an untrusted issuer, and hostname mismatch, checking the OpenSSL
verification error codes. It also exercises a stalled handshake deadline,
explicit socket cancellation, and a keyboard interrupt during real blocking
handshake I/O. It asserts descriptor/thread cleanup. Only the test routing and
trust-store fixtures are substituted; certificate/SNI/HTTP/timeout behavior is
real. Production loopback rejection and destination pinning are unchanged. These
tests require permission to bind a local listener and contact no external sites.
This is integration testing, not an external penetration test or an OS firewall.

Manual review covered application logging calls, parser dependency diagnostic
calls, public exception wrapping, crawler transport debug output and collection
audit serialization. PDFMiner debug events can contain full text; pdfplumber
metadata warnings and BeautifulSoup locator warnings can contain sensitive input.
Known parser namespaces now terminate at discard-only handlers within a scoped,
serialized context. Existing child handlers and warning hooks are restored after
success, exceptions and cancellation. Warnings are discarded before formatting;
only a fixed omission notice reaches the import result. Independent operational
loggers are unaffected. Public errors suppress the original exception traceback.
The application does not print HTTP debug headers, log cookies/authentication,
or include document bodies, paths, query URLs or raw exception strings in crawl
audits. Unknown error/event codes become `collection_failed`. The unused legacy
access-log helper discards raw source/status input and creates no automatic file.

Privacy regressions use real PDF debug/metadata diagnostics and HTML warnings,
plus injected tokens, cookies, passwords, private text and query URLs. They check
captured Python logs, directly attached parser handlers, warning capture, stdout,
stderr, formatted public tracebacks and serialized crawl audit payloads. Imported
records and explicitly requested browsing/exports intentionally retain content;
this does not redact or encrypt the research database.

OOXML preflight uses the standard library's streaming Expat parser with DTD,
entity and external-reference declarations refused, including UTF-16 documents.
It never extracts ZIP paths. Unsafe paths, symlink and duplicate members,
unsupported compression, encrypted flags and macro filenames are refused before
Office parsing. Expanded sizes/member counts are checked; XML is read in 64 KiB
chunks with a nesting limit. Worksheet coordinates/dimensions and actual row/cell
counts are checked before openpyxl can allocate wide rows or traverse sparse gaps.
Default `max_xml_depth` is 100 and `max_spreadsheet_columns` is 1024; maximum
worksheet row references are bounded by `max_records + 1` (including the header).
Inflated ranges, even on otherwise readable sheets, need trimming or splitting.
Corrupt CRCs/XML, invalid shared-string references and malformed PDF/Office
structures produce document-independent actionable errors. External Office
relationships are not fetched; no macros, scripts, OCR or shell repair is run.

The self-check now covers 23 in-process cases, adding current network-policy
IP/IPv6/userinfo/query/authorization checks and output filename validation to the
legacy smoke cases. It neither resolves live DNS nor creates a database.

Remaining security limits:

- Parser resource limits are guardrails, not a hard CPU/RAM sandbox. Native PDF,
  font/image, ZIP-directory and XML internals can consume resources before an
  application limit applies. For highly hostile documents, use OS isolation.
- Parser diagnostic containment assumes SpiderDeck's serial parsing and standard
  dependency loggers/warnings. Concurrent external handler reconfiguration,
  debugger/local-variable dumps, arbitrary plugins and hostile same-user processes
  are outside this boundary. The lock serializes SpiderDeck parser calls; warning
  hooks are process-wide and unrelated concurrent warnings could be omitted.
- DNS resolution duration, trusted OS routing and same-user filesystem tampering
  remain the documented transport/filesystem limits. Certificate validation uses
  configured trust roots and system time; active revocation checking is not added.
- No live-site crawl, authenticated/browser security test, fuzzing campaign or
  independent penetration test was performed. Those capabilities remain deferred.
- pip-audit covers known Python-package advisories, not unknown vulnerabilities,
  the Python interpreter, system OpenSSL, Expat or SQLite. Keep the OS/runtime
  patched separately. No new runtime dependency is needed for this increment.

Verification on 2026-10-25 (macOS, Python 3.13.4): the complete suite passed
**419 tests in 8.55 seconds**, including 7 real local TLS integration cases,
15 diagnostic/privacy cases and 54 malicious-document cases. The 23-case CLI
self-check passed. `verify.py` imported all required packages, `pip check` found
no broken requirements, and `pip-audit --local` reported no known vulnerabilities.
Installer shell syntax and `git diff --check` also passed. Initial sandbox runs
could not bind the HTTPS listener; the final full suite ran with local-listener
permission and skipped no TLS cases. These are measured test results and manual
code-review findings, subject to the limits above, not a security certification.


## V1 interactive approval, native input and configuration writes

Entering a URL performs only local syntax/hostname normalization. A previously
unapproved hostname must be explicitly approved for this run or saved after
confirmation; saved entries are not per-run collection authorization. Invalid
legacy entries stay inactive on disk and never automatically become approvals.
The user separately authorizes automated preflight GETs before any DNS/socket
work. The exact-host temporary configuration is passed through the unchanged
NetworkPolicy and pinned TLS transport; it grants no wildcard, scheme or redirect
exception. IP checks, TLS verification, robots, restriction detection, honest
User-Agent, rate limits and aggregate budgets remain enforced.

Preflight reserves an exclusive private audit file under output before networking.
It checks robots and one seed page, pauses without following links, and then needs
another user confirmation before continuing collection or persisting records.
The pause retains only bounded parser/response data. Seed/robots requests are
reused, not repeated; active preflight time, request counts and bytes count toward
collection budgets. Preflight additionally caps attempts at 8, redirects per chain
at 3, scheduled active duration at 20s, individual responses at 2 MiB, and aggregate
bodies at 4 MiB (configured lower limits take precedence). These are not a hard OS
DNS/CPU watchdog. The confirmation pause is excluded from active-work duration
without increasing the request/byte allowance. Later requests still re-resolve
and pin public IPs. Cancellation publishes only non-sensitive aggregate audit
fields; no seed records are saved unless final collection was authorized. Stored
pages accepted before a later failure remain additive, as in the previous flow.

Opening the browser is an optional explicit action after a successful public
access check. It uses a fixed macOS `open` argument list (stdlib browser selection
on other systems), with a revalidated query-free HTTP(S) URL. The browser itself
is an independent external application: its cookies, redirects and networking
are not controlled by the pinned crawler and are never read or reused by
SpiderDeck. This does not implement authenticated collection. Login/CAPTCHA,
robots denials, paywalls and restricted document viewers still require an
authorized export; no browser-session extraction was added.

Native file selection loads only on request. Existing NSOpenPanel/PyObjC or Tk
may supply the dialog; otherwise a fixed `osascript` script invokes macOS's
built-in choose-file panel. It accepts no untrusted script parameters. Selected
paths are returned as data and passed directly to the existing descriptor/file
validation and parsers; they never enter a shell command. A cancelled panel is
distinct from an unavailable/headless panel, so cancellation does not trigger a
text prompt. Imported documents are never automatically opened externally.
Read-only previews strip controls/bidirectional formatting and stay bounded;
file size is the validated snapshot size. Password/malformed/oversize/path errors
remain document-independent and do not expose selected paths in failure messages.
A source-exact SQLite filter prevents imported-source views from matching nearby
filenames. Record identifiers and database schema are unchanged.

Interactive settings can edit only hostname entries and the documented crawl
limits. They cannot enable local/private crawling, disable robots or introduce
credentials. Every persistent edit requires confirmation. The writer checks a
small owned regular configuration file without symlinks/hardlinks/shared-write
permissions, and an owned parent not writable by others. It validates the full
candidate with the existing loader, compares parsed before/after data to ensure
unrelated values are preserved, and edits only supported crawl values. Existing
comments outside changed values remain verbatim; comments inside a replaced
hostname array may be replaced. Unsupported TOML layouts are refused, never
wholesale reformatted. A 0600 exclusive backup preserves all original bytes,
then a 0600 temporary file is fsynced and atomically replaced. These explicitly
requested configuration files/backups are the exception to application-output
containment; databases, exports and collection audits still remain under output.

Advisory file locking coordinates SpiderDeck writers. Inode/content/mtime/ctime
snapshots detect stale dialogs, moved files and observed concurrent edits before
publication; users must reload and review again after conflict. Trusted ancestors
and cooperative editors are still required: POSIX rename has no universal
compare-and-swap against a hostile same-user editor changing the pathname during
the final check/replace interval. Locks are not a filesystem sandbox. Hidden
backup files remain private beside the selected configuration, are never
silently deleted and may contain any secrets previously present in that file.
Existing user changes were not discarded or automatically normalized.

Unreadable configuration is never silently replaced. An interactive Terminal
session can explicitly choose safe session defaults with no saved host approvals;
a separate Settings recovery confirmation backs up the original bytes and writes
documented defaults. It changes no database. Headless invalid-config startup
still exits with code 2. Missing/unsafe/symlink configuration is not auto-created
or overwritten; such paths remain read-only. Other configuration sections need a
restart after recovery; users should review the output location before importing.
All native dialog/browser tests are mocked. Visual macOS behavior requires the
manual checks in MANUAL_TESTING.md and is not claimed as automatically verified.

V1 verification on 2026-10-25: the complete suite passed **485 tests in 8.18s**,
including all 8 real loopback HTTPS cases and 65 focused V1 configuration/workflow
cases. The 23-case security self-check, dependency imports, `pip check`, shell
syntax and `git diff --check` passed. `pip-audit --local` reported no known
vulnerabilities. Tests mock native panel/browser interactions; visual macOS
acceptance checks remain unperformed. The preexisting parser CPU/RAM, OS DNS,
trusted-routing, same-user filesystem and known-advisory audit limits still apply.
Configuration locking uses POSIX `flock`; Windows support is not established.

## Research-engine extension: schema 3 and focused collection

The research feature reuses the existing pinned transport, robots handling,
resource budgets, static restriction checks, parser diagnostic guard, filesystem
writers and per-run authorization prompts. Topic text and page content cannot
approve hosts, write configuration, add headers or change network policy. Main
menu 0 adds project workflows without changing legacy shortcuts. Project web
collection is also disabled when the startup self-check fails. Each additional
seed has its own complete approval/preflight/start cycle and bounded run.

The focused heap stores at most the configured frontier, with canonical URL
deduplication and deterministic priority/depth/URL ties. Low-relevance exploration
is limited by mode plus the unchanged page/depth/request/time/byte/record budgets.
All fetched records, including rejected pages, consume those processing budgets.
Large scoring inputs are visibly retained for manual review, not asserted to be
strong matches. Relevance is lexical and heuristic; it grants no access rights,
source credibility, comprehensive coverage or peer-review status. Coverage counts
record matches, not independent studies, and can include exact copies.

HTML restrictions are checked on full visible text/metadata before main-region
selection. Structured content is derived as data, with aggregate text/count
budgets. Oversized base/href URLs cannot expand into an unbounded link list:
individual URLs are capped at 4096 characters, candidates at 10000 and aggregate
URL characters at two million, or stricter configured discovery bounds. Rejected
links grant no alternate destination. Nested paragraph/table previews share a
500000-character budget. The complete extracted text remains stored for accepted
records; raw HTML, scripts, macros and original document binaries are not executed
or copied into the database. Exact paragraph repetitions are reported, not removed.
Whitespace/NFC/main-region transformations are recorded. Sinhala/Tamil marks and
ZWJ/ZWNJ are preserved; terminal/bidi controls are omitted from readable views.
PDF replacement/unmapped glyph warnings do not claim that unflagged text is correct.
Missing DOCX core properties are not synthesized as source evidence.

Incremental collection accepts only If-None-Match/If-Modified-Since headers with
bounded printable ASCII values and no newline/control characters. Header validation
happens before DNS. No arbitrary request headers, credentials or cookies can enter
this path. Validators are keyed by the exact normalized URL and reference complete
persisted records. robots.txt is always requested afresh without cached validators.
Each conditional request still validates the complete DNS set, pins its destination,
verifies TLS, checks redirects, rate limits and budgets. Unsolicited/invalid 304s
fail closed. Cached traversal preserves nofollow, and response X-Robots restrictions
can block reuse. Cached evidence is rescored for the active project. Low-relevance
or partially retained pages are not cache entries. Quick Crawl stays uncached.
The cache is not evidence that permission remains granted: user authorization and
the supported network/access checks still apply on every run.

Schema 1/2 upgrades first validate the recognized old schema, then create a unique
0600 SQLite-backup snapshot under the owned output directory. Backup integrity and
record/import counts are checked. The migration is transactional; failed DDL/version
updates roll back rather than recreate the database. A read snapshot coordinates
backup/DDL; a conflicting upgrade can fail safely and must be retried. Migration
backups can require space comparable to the current database. Existing records,
IDs, timestamps, ideas and manifests are not rewritten. Older app versions refuse
schema 3; use the stopped-database recovery procedure in MANUAL_TESTING.md.

Projects link shared records through foreign keys. New exact content copies keep
their own provenance but refer to a canonical retained payload; full payload/type
comparison guards content-hash collisions. Effective record reads resolve those
references through static parameterized queries. Existing duplicate rows are not
compacted. FK and canonical-reference checks detect missing/chained references at
open; user-supplied databases are still unsupported. The app never deletes raw
records or canonical payloads. Explicit project deletion removes associations and
unreferenced assessment profiles, detaches collection history and retains shared
sources/records/files. It does not erase prior exports or provide secure deletion.

Assessment profiles are stored once per fingerprint. FTS5 is runtime-optional and
contentless, mapped to record IDs and maintained in the same import transaction.
It needs no trigger or persistent view. Literal Unicode search remains the default;
FTS queries are quoted as data, never arbitrary SQL/FTS operators. Foreign keys,
parameterization and executable-schema rejection remain enabled. No WAL, automatic
VACUUM or background indexing worker was added. Database/cache/export data remains
plaintext; ownership/0600 permissions and account/FileVault protections matter.

History stores fixed statuses and allowlisted aggregate counts, not header values,
page bodies, sensitive query parameters or raw exception strings. Source attribution
in the research database intentionally contains the user-chosen path/approved URL;
that is research data rather than diagnostic output. Source classifications are
unknown unless user-supplied, explicitly unverified evidence is recorded. Source
metadata is a source claim, not a citation verification service.

Project exports stream a SQLite read snapshot. JSON includes original/cleaned text,
structure, explanations and assessment profiles; it can contain personal research
data and should be shared deliberately. CSV quotes cells and neutralizes formulas,
including control/format-prefixed/fullwidth introducers. Markdown fences content
with a delimiter longer than any embedded backticks, escapes metadata markup and
omits terminal/bidi controls from readable output while retaining script joiners.
It does not generate summaries or execute extracted code.

Replacing an export requires explicit confirmation. Only an owned, private regular
file without hardlinks/symlinks is replaceable; a complete private backup is kept
before atomic replacement. Changes observed during writing abort replacement.
Trusted ancestors and cooperative same-user processes remain required: the final
check/rename is not an OS compare-and-swap against a hostile same-user process.
A failed export never silently discards project associations. Export filters are
explicit, counts are reported, and existing global exports keep their no-overwrite
behavior.

Remaining limitations are unchanged: this is not a hard CPU/RAM/DNS/OS sandbox,
certificate revocation service, authenticated/browser collector, independent
penetration test, semantic understanding system or secure-erasure tool. The new
source/score views and native-picker path have automated coverage, but visual
macOS acceptance remains manual. Synthetic relevance judgments and offline
transport benchmarks do not establish real-world relevance accuracy or internet
crawl throughput. No runtime dependency or remote AI service was introduced.


Migration and replacement backups are written privately to temporary names and
published only after their copy/validation step completes. A hard process crash
can leave private pending files; those are not trusted published backups. A
migration backup uses bounded SQLite page steps and a 120-second progress budget
(OS I/O stalls still have the documented native timing limits). Existing supervisor
idea counts are verified along with records/manifests. Project metadata, assessment
profiles and exported findings are read from one SQLite snapshot, including when
a legitimate WAL writer commits concurrently. Caller-side export filesystem errors
remain distinguishable from database failures so an existing filename cannot hide
or skip the explicit replacement confirmation.
