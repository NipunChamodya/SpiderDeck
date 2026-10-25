# Research engine implementation report

## Implemented behavior

Menu 0 manages research projects: create, open, edit, archive, confirmed deletion,
collection, document import, reassessment, history, search, readable evidence and
filtered Markdown/JSON/CSV export. Quick collection, local import and supervisor
ranking remain available through existing menu entries. No new dependencies.

The deterministic local scorer explains body/title/heading/phrase/token signals,
excluded terms and thresholds. Strict, Balanced and Discovery use a bounded
priority frontier; none grants hostname approval or changes transport security.
Original text and available source structure are preserved. Source classification
is unknown unless evidence or an explicitly unverified user choice is recorded.

## Database compatibility

Schema 3 adds projects, associations, shared assessment profiles, source/details,
history, exact-copy references, validator cache and optional contentless FTS5.
Known schema 1/2 databases receive a private SQLite backup before transactional
migration, with preserved record counts and integrity checks. Failure rolls back;
no silent database recreation. Existing user database was not migrated during
development. Project deletion preserves records and original files. New identical
payloads reference canonical data; legacy duplicate rows are not compacted.
Use storage APIs for effective payloads rather than reading copy placeholders.

## Actual verification

- Complete suite: **544 passed in 10.47 seconds**, including real local HTTPS
  certificate/timeout/cancellation tests and malicious-document regressions.
- Offline security self-check: PASS.
- Dependency import verification: all 11 required packages imported.
- pip check: no broken requirements.
- pip-audit: no known vulnerabilities found.
- git diff --check: passed.
- Piped terminal project creation/import/read/export integration executed.
- Native Finder/browser visual acceptance and live authorized collection were
  **not performed**. See MANUAL_TESTING.md.

## Measured performance and evaluation

Final traced synthetic 1,000-record run: scoring 0.1981 s; ingestion 0.6135 s;
first 20 literal results 0.0089 s; JSON export 0.2129 s; process RSS 52.77 MiB.
Report: output/research-performance-e59e970a30634556aee917c468ecf361.json.
PERFORMANCE.md includes all workload definitions, index plans and measurements.
Six authored judgments yielded Precision@3 0.6667, Recall@3 1.0, NDCG@3 1.0;
this is not evidence of general relevance accuracy. The optional TF-IDF
comparison and its limitations are recorded there.

## Beginner macOS workflow

1. In the repository Terminal run `source .venv/bin/activate`.
2. Run `python spiderdeck.py --plain --no-animation`.
3. Choose 0, create a project, review title-derived keyword suggestions, enter
   optional description/exclusions, choose a mode and confirm.
4. From its dashboard choose collection or document import. For each website
   review the exact hostname/scope and separately approve collection. Finder
   imports validate the selected document through existing parsers.
5. Browse evidence, search within the project, inspect original text and
   relevance explanations, then export Markdown, JSON or CSV.
6. Follow MANUAL_TESTING.md for isolated database setup, migration recovery,
   native-dialog checks, conditional collection and security cancellation tests.

## Remaining limitations

Lexical scoring can miss semantic/multilingual equivalents; there is no generated
summary, translation or learned model. Oversized scoring prefixes require review.
Each seed is a separate bounded, approved run; the cache does not authorize
requests and fresh robots checks remain mandatory. Metadata-only changes may
retain an existing content identifier. Historical duplicates are not compacted.
FTS phrase semantics differ from literal search. Coverage counts are not proof
of comprehensive research or independent evidence.

Local databases/exports contain private evidence and are not encrypted by this
application. OS-level isolation is still needed against hostile same-user
processes; Python checks are not a universal DNS/browser sandbox or revocation
service. Export backups and migrations require free disk space. Review SECURITY.md
for the existing transport, parser and filesystem limitations.

## Source and documentation files created or modified

- `MANUAL_TESTING.md`
- `PERFORMANCE.md`
- `README.md`
- `SECURITY.md`
- `benchmarks/research.py`
- `core/models.py`
- `core/storage.py`
- `core/text.py`
- `crawler/collector.py`
- `crawler/fetcher.py`
- `crawler/frontier.py`
- `exporters/records.py`
- `exporters/research.py`
- `handlers/local.py`
- `processing/__init__.py`
- `processing/content.py`
- `rank/supervisor_ranker.py`
- `research/__init__.py`
- `research/cache.py`
- `research/evaluation.py`
- `research/models.py`
- `research/relevance.py`
- `research/schema.py`
- `research/storage.py`
- `security/network_policy.py`
- `spiderdeck.py`
- `tests/fixtures/research_judgments.json`
- `tests/test_focused_research.py`
- `tests/test_ranking.py`
- `tests/test_research.py`
- `tests/test_research_export.py`
- `tests/test_research_ui.py`
- `tests/test_tls_integration.py`
- `ui/collection.py`
- `ui/display.py`
- `ui/importing.py`
- `ui/menu.py`
- `ui/research.py`

## Git status

All implementation changes remain uncommitted. Four preexisting tracked
`__pycache__` modifications were preserved. No commit, push or history rewrite
was performed. Ignored benchmark reports remain under output/.
