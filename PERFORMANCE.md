# Performance and reliability — Phase F

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
