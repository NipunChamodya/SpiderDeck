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
configured exact hostname and an explicit declaration of automated-collection
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

Verification uses offline DNS/socket wire fixtures, not live internet targets.
Tests validate pinning, rebinding, peer checks, TLS context requirements and
simulated verification failures; they do not constitute a real certificate-chain
handshake test, live-site penetration test or proof of complete SSRF security.

The self-check is an offline 11-case smoke test, not a network security audit.
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

## Phase G: initial adversarial regressions

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
Phase G remains in progress: real certificate-chain integration, parser diagnostic
privacy review, and broader malicious-document coverage remain follow-up work.
Dependency audit results cover known advisories in installed Python packages;
they do not audit the interpreter, system OpenSSL, SQLite or unknown vulnerabilities.
