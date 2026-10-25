# SpiderDeck V1 manual testing on macOS

These are instructions, **not completed manual test results**. Automated tests mock
native dialogs and browser launching; a person must verify focus, Finder panels,
Terminal prompts and browser handoff on the target Mac. Record macOS/Python
versions, PASS/FAIL and non-sensitive observations for each section. Never include
real document contents, credentials, tokens or cookies in a bug report.

## 1. Start safely

1. Open Terminal in the SpiderDeck folder. Run `source .venv/bin/activate` after
   installation with `bash install.sh`. Run `python verify.py` if unsure.
2. Start `python spiderdeck.py`. Expect a security-check result, then the existing
   SpiderDeck menu. Use arrow keys/Enter; menu 8 exits and menu 9 exports.
3. Also try `python spiderdeck.py --plain --no-animation`. Plain mode still opens
   the native picker from a local interactive macOS Terminal; it uses numbered
   terminal prompts. Quiet mode hides optional progress, not approvals/results.
4. For isolated test data/configuration, use this optional scratch setup:

   ```zsh
   SPIDERDECK_TEST_DIR="$(mktemp -d)"
   python -c 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); (p/"config.toml").write_text("[output]\ndir="+json.dumps(str(p/"output"))+"\n", encoding="utf-8")' "$SPIDERDECK_TEST_DIR"
   python spiderdeck.py --config "$SPIDERDECK_TEST_DIR/config.toml"
   ```

   Keep this Terminal open so the variable remains available. That directory is
   private; normal tests now use a separate database. Nothing here deletes your
   usual database. Stop SpiderDeck before making any database backup.

## 2. Finder-style document selection and preview

1. Create your own small UTF-8 text document with TextEdit (Format → Make Plain
   Text) containing `Computer vision, sensors, தமிழ், සිංහල`. Save it with spaces
   and Unicode in its filename, such as `Research தமிழ் notes.txt`.
2. Choose **2) Import a local document**. Expect a native macOS file-selection
   dialog without typing a path. Check that it appears in front of Terminal.
3. Select the file and choose **Open**. Expect the filename, type, byte size,
   extracted record and character counts, short readable preview, saved/duplicate
   counts and database location. No external document viewer should launch.
4. Choose **Browse imported records**. Verify the sample text and source. Choose
   **Search imported content** and enter `vision`; verify the source stays scoped.
5. Choose **Import another document** and import a second sample, then return to
   the main menu. Import the first again: existing stable IDs should be skipped;
   the original stored records must remain. Earlier versions at that same source
   path may appear in source-scoped browsing/searching.
6. Repeat with small documents you created: CSV with a header/data row, JSON,
   Markdown (`.md` or `.markdown`), HTML, XLSX from Excel/Numbers, DOCX from Word,
   and a text-based PDF. PDFs can warn when no usable text is present; there is
   no automatic OCR. Formulas/macros are not run and HTML scripts are not executed.
7. Choose Import again, then **Cancel** in the native panel. Expect `Import
   cancelled` and no typed-path prompt, parser work or new records.
8. If no panel can be supplied, expect a clear text-path fallback. Homebrew
   Python may lack `_tkinter`; the built-in macOS choose-file fallback should
   still work. A GUI-host/permission failure can make a manual path necessary.
   Do not grant unrelated browser-cookie or accessibility permissions.
9. Optional headless check: pipe `8` into `python spiderdeck.py --plain`, then
   try a short piped import session. No native panel should open when stdin/stdout
   are not terminals. SSH sessions likewise use text-path fallback.

## 3. Import errors and persistence

Use only disposable samples you created, not restricted or malicious real files.

1. Try an unsupported file using All Files if the panel permits it (or use the
   documented text fallback). Expect a supported-format explanation and no save.
2. Rename a small plain text sample to `.pdf` and import it. Expect a malformed
   PDF explanation with authorized-export guidance; no traceback/document text.
3. Try a password-protected PDF you own. Expect an authorized unlocked/text-export
   request, without password prompts or bypass attempts. Try a corrupt DOCX/XLSX
   copy; expect an actionable error without partial import.
4. Try a disposable file larger than the configured 20 MiB default, if practical.
   Expect a size-limit error before parsing/saving. Do not raise limits merely to
   force hostile files through. Automated fixtures cover resource-limit details.
5. Try a user-chosen symlink to a readable sample; provenance should resolve to
   the real file. Missing/moved files or unreadable copies should fail safely.
   Do not change permissions on your real research documents solely for testing.
6. Quit and restart with the same configuration. Main menu **3)** must retain
   imported records. Main menu **4)** should search `vision`, the source and type.
7. Main menu **9)**: export the sample to a new `sample-results.json`, then a new
   `sample-results.csv`. Check counts and UTF-8 content. Reusing either filename
   must be refused; existing exports must remain unchanged. Exported data is
   intentional content, not redacted diagnostic output. Share it deliberately.

## 4. Interactive website approval and collection

Use a public static HTTPS site you own or have explicit permission to collect.
A public website, browser login or university affiliation is not permission for
bulk collection. Do not use uncontrolled live sites as security test targets.

1. Choose **1) Authorized static web collection** and enter the complete HTTPS
   URL of the permitted page. Expect hostname, normalized page URL and scope.
   Entering it alone must not approve the hostname or contact the site.
2. For a new hostname choose **Cancel**. Expect no DNS/HTTP work or database save.
3. Repeat and choose **Approve for this run only**. Decline the access-check
   confirmation. Expect no requests. Restarting must not remember that hostname.
4. Repeat, approve this run and explicitly authorize access checks. Expect
   checking/access/fetch/extract stages. Checks fetch robots and one seed page;
   they do not follow discovered links yet. Inspect the displayed access result.
5. Decline browser opening and decline **Start collection**. Expect no records
   saved from the check. A private aggregate audit is expected under output;
   its counts may describe the seed that was read with your permission.
6. Repeat and choose **Save hostname for future use**. Read and confirm the
   configuration-write prompt. Expect a private backup beside the selected TOML
   file. The hostname alone should be saved, not the page URL/query/password.
7. Restart and re-enter the same page. It should recognize the saved hostname,
   but still ask for permission to check access and to start collection. A saved
   hostname must never silently authorize a run or its subdomains.
8. After successful checks, accept **Open in default browser**. Verify Safari,
   Firefox or Chrome opens the URL using the default macOS association. Check
   focus/return to Terminal. Nothing should copy cookies, credentials or sessions
   back into SpiderDeck. Declining browser opening must leave collection usable.
9. Confirm **Start collection**. Expect honest stage/count updates, final page,
   record/link/save/skip counts, outcome, database location and browse/search/export
   options. Verify persisted results after restart. The seed should not be
   requested twice just because you reviewed the confirmations.
10. Cancel with Ctrl+C during a prompt and separately during an actual permitted
    fetch. Expect safe cancellation, an aggregate audit when publishable, and no
    partial SQLite transaction. Previously committed data must remain.
11. Try `file:///etc/passwd`, `https://127.0.0.1/`, a credential-bearing URL or a
    URL with `?token=example`. They must be refused without echoing a secret.
12. On your own controlled site, try a robots-denied page, a cross-origin redirect,
    an access-denied/login page and an invalid certificate. Expect a safe stop and
    useful next action, never a bypass. These cases are also covered offline by
    automated fixtures. Do not create real credential-bearing test URLs.

Browser-launch failure is mocked automatically. If opening fails manually,
SpiderDeck should explain that collection can continue independently. Browser
session collection, CAPTCHA solving, interactive Google document viewers and
JavaScript rendering are unsupported; request an authorized export instead.

## 5. Interactive Settings

1. Choose **7) Settings**. Expect the existing read-only summary plus actions.
   Merely viewing settings must not create/open a database.
2. **View approved hostnames**: exact hostnames should appear. Invalid legacy
   URL entries are inactive, not automatically approved; their sensitive raw
   strings should not appear in this summary.
3. **Add approved hostname**: enter a hostname without `https://` or a path.
   Decline Save first; verify it is absent. Repeat and confirm Save; verify it
   persists after restart but still requires per-run authorization.
4. Try `localhost`, an IP, a wildcard or a complete URL. Expect refusal and no
   file write. No control should disable robots or allow private-network access.
5. **Remove approved hostname**: select the disposable approval, confirm, then
   verify it disappears. You can remove an inactive legacy entry by its numbered
   label without exposing the raw URL.
6. **Configure crawl limits**: change `max_pages` to a modest number and save.
   Try a negative timeout, `nan` or zero; expect refusal without changing saved
   settings. Byte-valued limits are explicitly labeled; timing values use seconds.
7. **Restore default crawl limits**: inspect the proposed values and confirm.
   Verify hostnames and unrelated sections remain intact. Each successful write
   should leave a hidden private `.spiderdeck-config-backup-*.toml` beside the
   config (Finder Cmd+Shift+Period shows hidden files). Backups are not deleted.
8. Optional conflict test on the scratch configuration only: open a settings
   action, then change that same scratch file in another editor before confirming.
   Expect a stale-change refusal. Choose **Reload saved crawl settings**, review,
   and retry. Never perform this experiment on important production settings.

## 6. Corrupt configuration recovery (scratch file only)

1. Exit SpiderDeck. Only if you created the scratch setup above, intentionally
   corrupt that disposable configuration:

   ```zsh
   printf 'broken = [' > "$SPIDERDECK_TEST_DIR/config.toml"
   python spiderdeck.py --config "$SPIDERDECK_TEST_DIR/config.toml"
   ```

2. In an interactive Terminal, expect a safe-defaults offer without raw TOML
   source. Decline first; the file must remain unchanged. Relaunch and accept:
   no hostnames should be approved. Do not import or browse data in this session.
3. Choose Settings → **Recover unreadable configuration**. Confirm only for the
   scratch file. Expect a private exact-byte backup and readable default TOML.
   No database should be modified. Headless invalid-config startup still exits 2.
4. Recovery resets the output setting to the documented default `output/`, not
   the former scratch location; quit immediately. Review settings before future
   data operations. To continue isolated tests, recreate the scratch configuration
   with the setup command in section 1. Do not delete your real output directory.
5. Unusual TOML layouts, missing files, symlink/hardlink/shared-writable configs,
   unsafe parent permissions or disk errors may disable saving rather than risk
   overwriting data. Run-only website approvals remain available.

## 7. Automated verification and reporting

```zsh
python -m pytest -q
python spiderdeck.py --security-check
python verify.py
python -m pip check
python -m pip_audit --local
```

The complete suite needs permission for its loopback-only HTTPS server. It does
not contact live university websites. pip-audit needs internet access for package
vulnerability metadata; no documents are uploaded. GUI focus, native layout,
VoiceOver/keyboard usability and default-browser handoff still need human checks.
Report which backend appeared (PyObjC, Tk or macOS built-in fallback), exact steps,
expected/actual behavior and sanitized messages; mark unperformed checks NOT RUN.

Automated baseline recorded on 2026-10-25: 485 tests passed, including 8 real local
HTTPS integration tests; all 23 self-check cases passed and pip-audit reported no
known vulnerabilities. This does not mark any native-dialog/browser/manual step
above as performed. The fallback follows Apple's documented
[choose-file dialog interface](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/PromptforaFileorFolder.html);
its real appearance/focus still needs testing on your macOS installation.

## 8. Research projects and focused evidence

These are additional manual instructions, not a claim of completed visual tests.
Existing menu numbers are preserved: **0 opens research projects; 8 exits**.

1. Launch from Terminal:

   ```zsh
   source .venv/bin/activate
   python spiderdeck.py
   ```

   For isolated acceptance, reuse the private scratch configuration in section 1.
   Do not edit or replace your real database for testing.
2. Choose **0 → Create project**. Enter a research title, optional description,
   reviewed comma-separated keywords and excluded topics. Suggestions are literal
   title words, not verified concepts. Select Balanced and confirm creation.
3. Expect a dashboard showing actual source/record/relevance/duplicate/failure
   counts, creation/modification times and coverage counts. A new project starts
   empty. Strong coverage means five matched records, not comprehensive knowledge.
4. Choose **Import documents** and select a self-created, on-topic file through the
   native panel. Verify linked/skipped counts. A deliberately unrelated sample can
   be skipped; Quick Import in main menu 2 remains available without topic filtering.
5. Choose **Browse evidence**, select a record and verify title/source/type, page or
   row reference when available, heuristic relevance, matched/missing concepts,
   explanation and extraction warnings. Read another content page if offered.
   Optional original extracted text must remain available. No summary is fabricated.
6. Set a source category only with a meaningful evidence note. Verify it is labeled
   user-supplied/unverified. Never mark peer review merely because a hostname looks
   academic. Check author/publication date only when the source actually supplies it.
7. **Search project**: try a literal keyword, Sinhala/Tamil text, source/type filter,
   UTC association/check date range and different sort orders. Check matching
   excerpts against stored original/cleaned text. Missing queries should show no
   results. Search settings can opt into FTS token/phrase matching if supported;
   literal mode retains substring behavior and is preferable for exact Unicode text.
8. **Export findings**: enter a filename without an extension, select Markdown,
   decline filters initially and inspect the result. Repeat with JSON and CSV.
   Test an explicit filtered export. Counts must reflect selected records; JSON
   includes original text/structure/assessment profiles. Do not share personal data
   unintentionally. Readable Markdown fences untrusted text rather than executing it.
9. Retry an existing project export name: decline replacement and verify it remains
   intact. Then explicitly consent on a disposable private export: a backup should
   remain beside the new export. Symlink/hardlink/unsafe names must not be replaced.
10. **Edit research settings**: rename, edit description/terms/exclusions and change
    mode. Try Strict/Balanced/Discovery and threshold validation. Old assessments
    should be identified as stale; **Reassess stored evidence** should refresh them
    without deleting records that are now low relevance. Scores are not probabilities.
11. **Archive / unarchive**: an archived project should not accept collection/imports.
    Open archived projects from the project list to inspect or unarchive them.
12. Create a second project and import the same evidence. Both projects should see
    their own assessments over shared records. Delete only a disposable project by
    typing `DELETE` and confirming. Other projects, raw records and original files
    must remain. History is detached, not erased; this is not secure deletion.

### Focused web collection and incremental checks

1. In a project choose **Collect authorized websites**. Use only a static site you
   own or have explicit automated-collection permission for. Expect the same
   hostname, access-check, browser and separate collection-start confirmations.
2. On your controlled site, provide an on-topic page linking to both topic research
   and sports/contact/navigation pages. Verify promising pages are prioritized.
   Strict requires a relevant seed, Balanced allows one low-relevance navigation
   hop, Discovery allows two, all within the configured depth/page/request limits.
3. Add another seed only through its own approval cycle. A link to a different host
   must never approve it automatically. Robots denials, redirects outside origin,
   invalid TLS, private DNS and access failures must still stop safely.
4. Recollect an authorized resource that supports ETag/Last-Modified. The second
   run may report an unchanged page on 304, rescore/reassociate cached evidence and
   save no new record IDs. robots and connection checks still run. If the server
   does not supply valid validators, an ordinary bounded download is expected.
5. Change that controlled resource's content and validators. Verify a new content
   version is retained alongside the old evidence, not overwritten. New versions
   mean changed content at the same source/type/location, not just a later timestamp.
6. Review collection history and counters. Unchanged is a subset of relevant/low/
   review outcomes, not an extra mutually exclusive page category. Exact content
   copies can count toward coverage; check sources for independence yourself.
7. Cancel preflight/start and during collection. Check no unapproved page was saved,
   accepted earlier evidence remains, and history/audits contain aggregate counts.
   Never bypass Google viewer restrictions, login, CAPTCHA or robots for this test.

## 9. Database migration and stopped-backup recovery

1. Before upgrading, stop SpiderDeck and keep your own backup if desired. Opening
   a data workflow on a recognized schema-1/2 database creates a private
   `migration-v1-*.sqlite3` or `migration-v2-*.sqlite3` snapshot under output before
   migration. Verify that file exists after the first data workflow. Fresh databases
   start at schema 3 and require no pre-migration snapshot.
2. Verify old browse/search/export and supervisor idea/ranking workflows still work.
   Do not test by altering `PRAGMA user_version` on your real database. Automated
   fixtures test real old schema layouts and interrupted migration rollback.
3. Raw SQL readers must understand new `record_copies` references. The Python
   `RecordStore.search/iter_records` APIs return full effective content. Historical
   rows are unchanged; new copies may have placeholder text/fields in raw SQL.
4. If recovery is needed, stop every SpiderDeck process first. Preserve the failed
   database and its sidecars for diagnosis; do not overwrite/delete your only copy.
   Create a separate private recovery directory, copy a trusted migration backup
   there as `spiderdeck.sqlite3` with private permissions, and point a separate TOML
   output configuration there. For example, replacing the backup argument with
   your actual trusted stopped-backup path:

   ```zsh
   SPIDERDECK_RECOVERY_DIR="$(mktemp -d)"
   cp -p "/absolute/path/to/trusted/migration-v2-BACKUP.sqlite3" "$SPIDERDECK_RECOVERY_DIR/spiderdeck.sqlite3"
   python -c 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); (p/"recovery.toml").write_text("[output]\ndir="+json.dumps(str(p))+"\n",encoding="utf-8")' "$SPIDERDECK_RECOVERY_DIR"
   python spiderdeck.py --config "$SPIDERDECK_RECOVERY_DIR/recovery.toml"
   ```

   This opens a separate recovery copy and can migrate it again. It never replaces
   your original database. An older schema-2 application may read the version-2
   backup but will refuse schema 3. Keep backups private; they contain source data.
5. Full disk, locks, corrupt/unknown layouts or reference-integrity errors should
   produce a safe error, not silently recreate the database. Missing native dialogs
   still use the headless/path fallback documented earlier.

## 10. Reproduce research benchmarks

```zsh
python -m pytest -q
python spiderdeck.py --security-check
python -m benchmarks.research --records 1000 --output-dir output
python -m benchmarks.run --rows 1000 --repeats 1 --output-dir output
python verify.py
python -m pip check
python -m pip_audit --local
```

Reports contain generated fixtures only. The research benchmark includes Python
allocation tracing and an offline in-memory HTTP fixture, not live network speed.
It verifies projects, parsing, relevance, insert/reimport/versions/copies, search,
exports and authored-fixture IR metrics. It does not open your existing database.
Actual native dialog focus, browser handoff, multilingual font rendering and
long-session responsiveness still require a person using the target Mac.
