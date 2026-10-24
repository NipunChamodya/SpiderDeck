# Security model and current boundaries

Phase A handles explicitly selected local regular files. It does not perform
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

The output validator now uses path component containment rather than a string
prefix, rejects absolute paths and traversal, and resolves symlinks. It does not
atomically open files: future persistence/export implementations must protect
against concurrent symlink replacement and accidental overwrites. Local inputs
may legitimately reside outside the output directory.

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

## Dependency audit observed during Phase A

`python -m pip_audit --local` completed and reported two known vulnerabilities
in installed `pdfminer-six==20231228`: `PYSEC-2026-1762` (fix listed as
`20251107`) and `PYSEC-2026-1761` (fix listed as `20251230`). This environment
is not dependency-audit clean. Upgrade and compatibility-test the pdfplumber /
pdfminer stack before processing untrusted PDFs. Existing runtime pins were not
silently changed in this phase. The audit reports installed distributions and
does not establish that every installed package matches requirements.txt.
