# Performance and reliability

The Phase F measurements below are historical schema-2 observations. Current
research-engine schema-3 measurements and commands follow at the end.

SpiderDeck remains sequential and local-first. This phase measures existing work,
removes repeated allocations/computation, and fixes bounded-input behavior. It
adds no production worker pool, remote service, model download or dependency.
The database schema remains version 2.

## Reproduce measurements

From the repository with its virtual environment active:

```zsh
python -m benchmarks.run --rows 5000 --repeats 3
python -m benchmarks.run --rows 5000 --repeats 1 --mode memory --jobs import_csv save reimport json_export rank_warm pdf_limit
python -m benchmarks.run --rows 5000 --repeats 1 --mode profile --jobs rank_warm reimport
python -m benchmarks.run --rows 20000 --repeats 1 --jobs import_csv save reimport search json_export
```

The command prints a new `output/performance-<id>/report.json` path. By default it
uses `[output].dir`; an explicit `--output-dir PATH` selects the benchmark output
root instead. Relative explicit paths use the current working directory. Each
sample gets a fresh, private synthetic workspace and child interpreter. Timed
workloads are sequential, not parallel. CSV, databases, API-free CLI sessions and
exports are generated solely for the benchmark; real documents and the existing
SpiderDeck database are never opened. Normal runs remove only their newly created
synthetic workspace and retain the report. Use `--keep-workloads` to retain
fixtures/databases deliberately. An interrupted/killed worker may leave synthetic
artifacts under that run directory. Existing files are never overwritten.

Allowed sizes are 1–20,000 CSV rows and 1–10 repeats. Ranking uses up to 1,000
candidates and four synthetic ideas; other pipeline cases use the requested row
count. The PDF-limit case generates 100 pages with a two-page import limit.
Outcome counts are validated before a sample is considered successful. Worker
failures/timeouts are reported as failures rather than fast successful results;
the CLI exits nonzero if any sample fails. Each sample has a 180-second worker
limit. This Unix measurement tool is tested on macOS Apple Silicon; it is not a
Windows profiler.

Reports include wall/CPU times, process RSS high-water observations, configuration
size/mode, dependency versions, and source-file SHA-256 fingerprints. The `startup`
case includes a separate CLI interpreter, startup self-check and immediate exit.
The `idle` case measures CPU while a plain-mode CLI waits about one second for
input; it verifies that no database was created. It does not measure every
interactive terminal or a long idle session.

`time` mode is uninstrumented at the action boundary. `memory` uses
[tracemalloc](https://docs.python.org/3.13/library/tracemalloc.html) only during the
measured action, excluding input/setup allocations already alive and native
allocations. `profile` uses [cProfile](https://docs.python.org/3.13/library/profile.html)
for hotspot diagnosis; profile timings are not used as speed benchmarks. Process
high-water RSS from [resource](https://docs.python.org/3.13/library/resource.html)
includes untimed setup and native allocations, so it is not incremental phase
memory. Darwin RSS is normalized from bytes; Linux from KiB. CLI-child RSS is
reported separately from the benchmark worker where available.

OS/filesystem/bytecode caches, background work and tracing affect observations.
Run comparisons on an otherwise quiet machine with equivalent dependencies and
profiling environment. No CI wall-time threshold is enforced. These measurements
are not hard CPU/RAM limits, scientific confidence intervals, relevance accuracy
results or live crawl throughput measurements.

## Observed development results

Environment: macOS arm64, Python 3.13.4, SQLite 3.50.1, scikit-learn 1.5.2,
NumPy 2.5.4, SciPy 1.18.1; patched pdfplumber 0.11.10/pdfminer.six 20260107.
Timing entries below are medians of three fresh-worker samples, with fixture/setup
excluded except where explicitly noted. CSV/persistence/export use 5,000 rows;
ranking uses 1,000 candidates and four ideas.

| Action | Before (seconds) | After (seconds) |
| --- | ---: | ---: |
| CSV import | 0.0879 | 0.0855 |
| First transactional save | 0.1547 | 0.1038 |
| Storage reimport (parsing excluded) | 0.1179 | 0.0489 |
| Keyword count plus first result page | 0.0445 | 0.0436 |
| JSON export | 0.1633 | 0.1673 |
| CSV export | 0.1695 | 0.1576 |
| Ranking after library loading | 0.2669 | 0.0502 |
| Ranking including lazy imports | 1.4666 | 0.9997 |
| CLI startup/self-check/immediate exit | 0.1431 | 0.1513 |

Warm ranking improved about 5.3× and storage reimport about 2.4× on these fixtures.
Unchanged startup/search/export paths show normal variation; no general speedup
is claimed for those paths. Reimports still parse and validate their input first
in the menu; the storage-only number does not include that separate import cost.

Single traced observations for the same fixture:

| Python allocations during action | Before peak (MiB) | After peak (MiB) |
| --- | ---: | ---: |
| CSV import | 20.01 | 7.51 |
| First save | 1.52 | 1.00 |
| Warm ranking | 1.77 | 1.78 |
| JSON export | 0.25 | 0.79 |

These are Python allocation peaks, not total physical RAM usage. The small export
increase remains below 1 MiB in this observation; that path was not optimized.
The default file read previously reserved up to 20 MiB even for a small input;
using the checked size removes that avoidable allocation. CSV decoding now uses
TextIOWrapper incrementally over a bounded byte snapshot instead of a complete
decoded string plus StringIO's character buffer. Records remain materialized for
atomic import; this is not an unlimited streaming ingestion API.

The plain idle samples consumed roughly 0.01–0.09% of one CPU core over approximately
one-second waits after the changes. Such short samples are noisy and do not prove
long-term idle behavior. No background process was added to the application.

A separate 20,000-row run completed import (0.355 s), first save (0.638 s), storage
reimport (0.200 s), search (0.175 s) and JSON export (0.707 s). Observed worker RSS
high-water marks were about 60–68 MiB, including setup. This is one synthetic run,
not a universal large-document memory bound.

## Changes and compatibility

- Ranking compiles field aliases once per comparison, normalizes record columns
  once, and reuses compact token-boundary strings. Temporary caches are bounded
  by existing input limits and disappear after each comparison.
- Sparse TF-IDF explanations are constructed only for returned top-K candidates,
  preserving the previous scores, matched-term order, ties and provenance. A
  pre-optimization synthetic snapshot protects full result compatibility. It is
  not labeled suitability ground truth.
- Storage serializes fields/metadata directly instead of deep-copying the whole
  record. Duplicate IDs still undergo full content/location collision checks;
  hashing/timestamp work is skipped only after equality is established. The
  public `ExtractedRecord.to_dict()` deep-copy/timestamp contract is unchanged.
- Inputs open with no-follow/nonblocking flags, then undergo regular-file/size
  checks on the descriptor. An explicitly chosen symlink is still resolved and
  accepted; a symlink substituted after validation is refused. FIFO replacement
  cannot stall the reader. Size/mtime/ctime changes during snapshot reading cause
  a stable-file retry error rather than a partial import.
- PDF iteration is lazy and each page closes promptly. The former eager page
  property/cleanup constructed 200 wrappers for the 100-page/two-page-limit
  fixture; the new implementation constructs two, then refuses the oversized
  document. Permission checks precede page iteration and no OCR is performed.
  Parser metadata/xref setup can still scale with document structure; this is not
  a hostile-PDF sandbox. The implementation is tested against the pinned PDF stack.

Search, export ordering, SQL parameterization, rollback, schema handling, access
restrictions and the network destination/rate policies remain unchanged. No new
index/migration or concurrency was introduced without a measured need.


## Research-engine measurements — schema 3

Environment: macOS arm64, Python 3.13.4, SQLite 3.50.1. One fresh-process
observation with 1,000 synthetic records; actions include `tracemalloc`, so times
are traced diagnostics, not uninstrumented throughput claims. Input/setup memory
already alive at each action boundary is excluded from Python allocation peaks.
Process RSS includes setup/native allocations and earlier actions. No live-site
latency, DNS/TLS throughput, native-panel rendering or default-browser timing is
claimed. Tests separately exercise real loopback TLS/certificate/304 behavior.

Reproduce (generates private temporary workloads and a new private report only):

```zsh
python -m benchmarks.research --records 1000 --output-dir output
python -m benchmarks.run --rows 1000 --repeats 1 --output-dir output
```

The research benchmark accepts 1–2,000 records. It verifies project association,
exports, changed versions and exact copies before reporting success. Workloads
never open the user's existing SQLite database; scratch files are removed and
reports retained. It adds no production worker pool. The legacy benchmark's
fresh-worker isolation and bounded options remain available.

Report: `output/research-performance-bf7034150c1149c180658db2031c3509.json`.

| Traced action | Wall seconds | Python allocation peak (MiB) |
| --- | ---: | ---: |
| Create project | 0.0013 | 0.013 |
| Extract 1,000 JSON records | 0.0650 | 1.482 |
| Score 1,000 records | 0.1995 | 0.792 |
| First project ingestion | 0.6031 | 2.084 |
| Unchanged project reimport | 0.5319 | 1.899 |
| Preserve 1,000 new content versions | 0.6321 | 1.934 |
| Link 1,000 cross-source exact copies | 0.6841 | 1.900 |
| Literal project search, first 20 | 0.0089 | 0.143 |
| FTS project search, first 20 | 0.0059 | 0.137 |
| Markdown export, 1,000 records | 0.2984 | 0.049 |
| JSON export, 1,000 records | 0.2274 | 0.245 |
| CSV export, 1,000 records | 0.1192 | 0.172 |
| Offline seed + robots fixture (cold HTML import) | 0.8487 | 6.233 |

Observed process RSS high-water: **50.27 MiB**.
The final synthetic database includes 1,000 initial records, 1,000 changed versions
and 1,000 exact copies referencing retained payloads. It occupied
**11.05 MiB**, including indexes/structures/assessments;
its raw text/fields columns contained 391,120 characters
including copy placeholders. This is not a maximum application memory/storage bound.

Before adding the location index/profile normalization, the same 1,000-record
traced development workload observed reimport at 0.7327 s and changed-version
insertion at 0.6772 s (`research-performance-63e98b68bcd24c5aa804518b8bc00d57.json`).
After changes, those actions measured 0.5319 s
and 0.6321 s. These are single development
observations across several changes, not isolated-index causal evidence or a
statistical/general speedup claim. Query plans independently confirm use of
`project_record_score` for ranked pagination and the covering `records_location`
index for source/type/location version lookup.

Literal search and FTS have different semantics, so their times are not a claim
that one is always better. FTS is runtime-checked, contentless and optional;
literal NFC/casefolded search remains default. Date and reverse-association
indexes support project filters without indexing every project-specific payload.
Assessment profiles are fingerprinted once, new exact payload copies share
canonical data, and original stored rows are not rewritten. No WAL or automatic
VACUUM was introduced: serial operation and no measured benefit do not justify
new sidecar/write behavior. Legacy duplicates/derived source structures are not
physically compacted. Reassessment is bounded by record pages, not a global
all-record Python list; exports hold one read snapshot across project metadata,
profiles and findings, even when another WAL writer commits.

The legacy 11-workload benchmark also ran successfully with 1,000 rows and one
repeat in `output/performance-37dd078ed15c4e02aaeddb42d61feed4/report.json`.
Its uninstrumented observations included CSV extraction 0.0176 s, first save
0.0232 s, unchanged save 0.0107 s, search 0.0114 s, JSON export 0.0349 s, CSV export
0.0353 s, warm supervisor ranking 0.0517 s, cold ranking 1.4237 s and startup
0.1957 s. These are observations of existing workloads, not improvements over
the older 5,000-row table above.

## Relevance evaluation (authored synthetic judgments only)

`tests/fixtures/research_judgments.json` contains six explicitly authored examples
and their manual labels. The rule requires both phishing detection and a
WebAssembly implementation. There are two relevant examples; adjacent-only,
excluded/gaming, unrelated and empty examples are negative under that rule.
This is not real publication data, expert external ground truth or a held-out
claim about general research accuracy.

The benchmark actually computed Precision@3 = **0.6667**,
Recall@3 = **1.0000** and NDCG@3 = **1.0000**.
The first two results were the two labeled relevant examples. One adjacent
negative appears in the top three; lexical relevance does not establish
source quality or semantic correctness. DCG uses binary gains discounted by
`log2(rank+1)` and normalizes by the ideal ordering; precision divides by K.
The fixture hash is `4fbfbb76be5e39c930a0178f1d983407e5b8e4cb064a793bc59d84f215035829`. No general relevance-accuracy number
or fabricated real-world evaluation is reported.


### Explicit TF-IDF comparison

```zsh
python -m benchmarks.research --records 1000 --output-dir output --compare-tfidf
```

This optional comparator uses the already-installed scikit-learn library, fitted
only to the query plus six authored examples. It does not alter the production
scorer or fit a growing crawl corpus. In the recorded experiment
`output/research-performance-e85997cf434c4db683418758023024b8.json`, unigram TF-IDF
cosine yielded Precision@3 0.6667, Recall@3 1.0000,
and NDCG@3 0.9197. It ranked the adjacent negative second and one
relevant example third. The default heuristic ranked the two relevant examples
first on this fixture. This small authored fixture does not establish general
superiority; additional independently labeled research data is needed.

The traced cold comparison (imports plus fitting/ranking) took 2.7155 s
and peaked at 66.17 MiB of Python allocations. Whole-process
RSS high-water reached 191.45 MiB, including other workload
setup/native libraries. These are cold-run observations, not incremental native
memory or universal complexity bounds. The default topic scorer stays fixed and
page-independent as new pages arrive; thresholds do not shift with corpus IDF.
The existing bounded batch supervisor ranker continues to use TF-IDF unchanged.

## Final verification observation

The final 1,000-record traced run is
`output/research-performance-e59e970a30634556aee917c468ecf361.json`.
It measured scoring 0.1981 s, first ingestion 0.6135 s, first 20 literal
search results 0.0089 s, JSON export 0.2129 s, and process RSS high-water
52.77 MiB. Run-to-run variation applies; these are synthetic observations,
not live-network latency or a guaranteed memory ceiling.
