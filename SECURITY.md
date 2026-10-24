# Security model and current boundaries

The application handles explicitly selected local regular files. It does not perform
network collection, render browser content, fetch linked assets, execute macros,
or run document-supplied commands. No remote AI services are used. Import failures
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

Network collection remains unavailable. URL preflight validation now requires
an allowlist, rejects userinfo, checks all IPv4/IPv6 DNS results, and fails closed
on resolution errors. It still has DNS time-of-check/time-of-use weaknesses and
is not a network transport policy.
Before enabling web access, require explicit target authorization and allowlisting,
validate every DNS result and redirect, pin approved destination IPs at transport
level, and enforce timeouts, robots, rates, content limits and stop conditions.
Browser interception alone cannot provide a destination-IP guarantee.

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
