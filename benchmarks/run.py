"""Run from the repository: python -m benchmarks.run --rows 5000 --repeats 3.

Every sample runs in a fresh child process with its own generated fixture and DB.
No user documents, application database, network targets or external services are used.
"""
from __future__ import annotations

import argparse
import cProfile
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import pstats
import resource
import selectors
import shutil
import sqlite3
import statistics
import subprocess
import sys
import time
import tracemalloc
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.config import load_config
from security.filesystem import new_output_text, open_output_directory, output_directory, output_filename, verify_directory

ROOT = Path(__file__).resolve().parents[1]
JOBS = ("import_csv", "pdf_limit", "save", "reimport", "search", "json_export", "csv_export", "rank_cold", "rank_warm", "startup", "idle")
SUBJECTS = ("computer vision fish sensors", "wireless csi fall interference",
            "webassembly phishing browser security", "digital evidence image provenance")


def child_directory(root: Path, prefix: str) -> Path:
    name = output_filename(prefix + "-" + uuid4().hex)
    with open_output_directory(root) as descriptor:
        os.mkdir(name, mode=0o700, dir_fd=descriptor)
        verify_directory(root, descriptor)
    return root / name


def fixture(root: Path, rows: int) -> Path:
    with new_output_text(root, "synthetic.csv") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "Expertise", "Notes"])
        for index in range(rows):
            writer.writerow([f"Synthetic researcher {index}", SUBJECTS[index % 4],
                             "Synthetic local fixture. නිපුන් தமிழ். " * 2])
    return root / "synthetic.csv"


def pdf_fixture(pages: int = 100) -> bytes:
    """Small generated text PDF with a shared content stream; no embedded actions."""
    font, contents = pages + 3, pages + 4
    kids = " ".join(f"{index + 3} 0 R" for index in range(pages))
    stream = b"BT /F1 12 Tf 50 750 Td (Synthetic research text) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode()]
    objects.extend(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                   f"<< /Font << /F1 {font} 0 R >> >> /Contents {contents} 0 R >>".encode()
                   for _ in range(pages))
    objects.extend([b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                    f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"])
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, item in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + item + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode())
    return bytes(data)


def rss_bytes(usage: Any) -> int:
    return int(usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024))


def measure(action: Callable[[], dict], mode: str) -> dict:
    profiler = cProfile.Profile() if mode == "profile" else None
    if mode == "memory":
        tracemalloc.start()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started, cpu_started = time.perf_counter(), time.process_time()
    try:
        outcome = profiler.runcall(action) if profiler else action()
        wall, cpu = time.perf_counter() - started, time.process_time() - cpu_started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {"wall_seconds": wall, "cpu_seconds": cpu + after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                  "process_peak_rss_bytes": rss_bytes(resource.getrusage(resource.RUSAGE_SELF)),
                  "child_peak_rss_bytes": rss_bytes(after) if after.ru_maxrss else None, "outcome": outcome}
        if mode == "memory":
            result["python_peak_bytes"] = tracemalloc.get_traced_memory()[1]
        if profiler:
            stream = io.StringIO()
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(25)
            result["profile"] = stream.getvalue()
        return result
    finally:
        if mode == "memory":
            tracemalloc.stop()


_IDLE_CODE = '''
import builtins,json,sys,time
import spiderdeck
original = builtins.input
def measured_input(prompt):
    wall,cpu=time.perf_counter(),time.process_time()
    print("BENCH_READY",flush=True)
    answer=original(prompt)
    print("\\nBENCH_IDLE:"+json.dumps({"wall_seconds":time.perf_counter()-wall,"cpu_seconds":time.process_time()-cpu}),flush=True)
    return answer
builtins.input=measured_input
raise SystemExit(spiderdeck.main(["--quiet","--plain","--config",sys.argv[1]]))
'''


def cli_session(root: Path, *, idle: bool) -> dict:
    config_path = root / "config.toml"
    untouched = root / "database-must-not-open"
    with new_output_text(root, config_path.name) as handle:
        handle.write("[output]\ndir=" + json.dumps(str(untouched)) + "\n")
    if not idle:
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "spiderdeck.py"), "--quiet", "--plain", "--config", str(config_path)],
                                   input="8\n", capture_output=True, text=True, timeout=30, cwd=ROOT, check=True)
        if "Goodbye." not in completed.stdout or untouched.exists():
            raise ValueError("Startup did not exit cleanly without data access.")
        return {"exit_code": completed.returncode, "database_created": False}
    process = subprocess.Popen([sys.executable, "-B", "-c", _IDLE_CODE, str(config_path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
    try:
        pending = b""
        deadline = time.monotonic() + 15
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while b"BENCH_READY" not in pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("Idle prompt did not become ready.")
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError("Idle child exited before the prompt.")
                pending += chunk
        time.sleep(1.0)  # Measurement interval; not application rendering or workload concurrency.
        stdout, _ = process.communicate(b"8\n", timeout=15)
        transcript = (pending + stdout).decode("utf-8")
        line = next(line for line in transcript.splitlines() if line.startswith("BENCH_IDLE:"))
        observed = json.loads(line.split(":", 1)[1])
        if process.returncode != 0 or untouched.exists():
            raise ValueError("Idle session failed or opened data.")
        return {"idle_wall_seconds": observed["wall_seconds"], "idle_cpu_seconds": observed["cpu_seconds"],
                "idle_cpu_percent_of_one_core": observed["cpu_seconds"] / observed["wall_seconds"] * 100,
                "database_created": False}
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def worker(job: str, root: Path, rows: int, mode: str, *, keep_workloads: bool = False) -> dict:
    validate_options(rows, 1, [job], mode)
    if not keep_workloads and not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError("Safe synthetic workspace cleanup is not available on this platform.")
    work = child_directory(root, job)
    fingerprints = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        "handlers/local.py", "core/storage.py", "rank/supervisor_ranker.py", "spiderdeck.py", "benchmarks/run.py")}
    try:
        result = workload(job, work, rows, mode)
        validate_outcome(job, rows, result["outcome"])
        result["code_sha256"] = fingerprints
        return result
    finally:
        if not keep_workloads:
            # Only the fresh, uniquely created synthetic directory is removed.
            # fd-based rmtree does not follow symlinks to existing user data.
            shutil.rmtree(work)


def validate_outcome(job: str, rows: int, outcome: dict) -> None:
    matches = (rows + 3) // 4
    expected = {
        "import_csv": {"records": rows}, "save": {"inserted": rows, "duplicates": 0},
        "reimport": {"inserted": 0, "duplicates": rows, "reimported": True},
        "search": {"matches": matches, "page_records": min(20, matches)},
        "json_export": {"exported": rows}, "csv_export": {"exported": rows},
        "pdf_limit": {"limit_enforced": True},
        "startup": {"exit_code": 0, "database_created": False}, "idle": {"database_created": False},
    }
    if job.startswith("rank_"):
        required = {"candidates": min(rows, 1000), "ideas": 4,
                    "returned_matches": 4 * min(rows, 10)}
    else:
        required = expected[job]
    if any(outcome.get(key) != value for key, value in required.items()):
        raise ValueError("Synthetic benchmark outcome was incorrect; timings are not valid.")


def validate_options(rows: int, repeats: int, jobs: list[str], mode: str) -> None:
    if (type(rows) is not int or not 1 <= rows <= 20000 or type(repeats) is not int or not 1 <= repeats <= 10
            or not jobs or len(jobs) > len(JOBS) or any(job not in JOBS for job in jobs)
            or len(set(jobs)) != len(jobs) or mode not in {"time", "memory", "profile"}):
        raise ValueError("Invalid benchmark workload, mode or repeat count.")


def workload(job: str, work: Path, rows: int, mode: str) -> dict:
    if job in {"startup", "idle"}:
        return measure(lambda: cli_session(work, idle=job == "idle"), mode)
    from core.storage import RecordStore, SearchFilters
    from handlers.local import import_document
    if job == "pdf_limit":
        from core.config import ImportConfig
        from handlers.local import DocumentImportError
        from pdfplumber.page import Page
        from unittest.mock import patch
        with new_output_text(work, "synthetic.pdf") as handle:
            handle.buffer.write(pdf_fixture())
        original = Page.__init__
        count = 0
        def counted(page, *args, **kwargs):
            nonlocal count
            count += 1
            return original(page, *args, **kwargs)
        def limited_pdf() -> dict:
            with patch.object(Page, "__init__", counted):
                try:
                    import_document(work / "synthetic.pdf", ImportConfig(max_pdf_pages=2))
                except DocumentImportError as exc:
                    if "max_pdf_pages" not in str(exc):
                        raise
                    return {"limit_enforced": True, "page_wrappers_constructed": count, "document_pages": 100}
                raise ValueError("PDF page limit was not enforced.")
        return measure(limited_pdf, mode)
    source = fixture(work, rows)
    if job == "import_csv":
        return measure(lambda: {"records": len(import_document(source).records)}, mode)
    imported = import_document(source)
    store = RecordStore(work / "database")
    if job == "save":
        return measure(lambda: asdict(store.save_import(imported)), mode)
    store.save_import(imported)
    if job == "reimport":
        return measure(lambda: asdict(store.save_import(imported)), mode)
    if job == "search":
        def search() -> dict:
            filters = SearchFilters(keyword="vision", source_type="csv")
            return {"matches": store.count(filters), "page_records": len(store.search(filters, limit=20))}
        return measure(search, mode)
    if job in {"json_export", "csv_export"}:
        from exporters.records import export_records
        kind = job.split("_", 1)[0]
        return measure(lambda: {"exported": export_records(store.iter_records(), work, "records." + kind, kind)}, mode)
    from rank.models import ResearchIdea
    from rank.supervisor_ranker import rank_records
    candidates = store.search(limit=min(rows, 1000))
    ideas = [ResearchIdea(title=subject, keywords=tuple(subject.split())) for subject in SUBJECTS]
    if job == "rank_warm":
        rank_records(candidates, ideas)
    def rank() -> dict:
        results = rank_records(candidates, ideas)
        return {"candidates": results[0].candidate_count, "ideas": len(results),
                "returned_matches": sum(len(result.matches) for result in results)}
    return measure(rank, mode)


def run(output_dir: Path, *, rows: int, repeats: int, jobs: list[str], mode: str,
        keep_workloads: bool = False) -> Path:
    validate_options(rows, repeats, jobs, mode)
    root = output_directory(output_dir)
    run_dir = child_directory(root, "performance")
    samples = []
    failed = False
    for job in jobs:
        for repeat in range(repeats):
            command = [sys.executable, "-B", "-m", "benchmarks.run", "--worker", job,
                       "--output-dir", str(run_dir), "--rows", str(rows), "--mode", mode]
            if keep_workloads:
                command.append("--keep-workloads")
            try:
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                samples.append({"job": job, "repeat": repeat + 1, "status": "failed", "error": "worker_timeout"})
                failed = True
                continue
            if completed.returncode:
                samples.append({"job": job, "repeat": repeat + 1, "status": "failed", "exit_code": completed.returncode})
                failed = True
                continue
            sample = json.loads(completed.stdout)
            samples.append({"job": job, "repeat": repeat + 1, "status": "ok", **sample})
    summary = {}
    for job in jobs:
        valid = [sample for sample in samples if sample["job"] == job and sample["status"] == "ok"]
        if valid:
            summary[job] = {"median_wall_seconds": statistics.median(sample["wall_seconds"] for sample in valid),
                            "max_process_peak_rss_bytes": max(sample["process_peak_rss_bytes"] for sample in valid)}
            if mode == "memory":
                summary[job]["max_python_peak_bytes"] = max(sample["python_peak_bytes"] for sample in valid)
    versions: dict[str, str | None] = {}
    for name in ("scikit-learn", "numpy", "scipy", "pdfplumber", "pdfminer.six"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    report = {"schema_version": 1, "status": "failed" if failed else "ok", "rows": rows, "repeats": repeats,
              "keep_workloads": keep_workloads,
              "mode": mode, "environment": {"python": platform.python_version(), "platform": sys.platform,
                    "machine": platform.machine(), "sqlite": sqlite3.sqlite_version,
                    "packages": versions},
              "samples": samples, "summary": summary,
              "limitations": ["Synthetic local data only; no relevance-accuracy evaluation or live network benchmark.",
                    "RSS is a process high-water mark including untimed setup, not incremental phase memory.",
                    "Python allocation peaks exclude existing setup data and native allocations.",
                    "Profile/memory instrumentation changes timings; compare time-mode runs separately.",
                    "Ranking is capped at 1000 input records; cold ranking includes lazy library imports.",
                    "Child interpreters isolate measurements; application workloads remain sequential."]}
    with new_output_text(run_dir, "report.json") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    return run_dir / "report.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--jobs", nargs="+", choices=JOBS, default=list(JOBS))
    parser.add_argument("--mode", choices=("time", "memory", "profile"), default="time")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--keep-workloads", action="store_true", help="Retain synthetic fixtures and databases for inspection")
    parser.add_argument("--worker", choices=JOBS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.rows <= 20000 or not 1 <= args.repeats <= 10:
        parser.error("rows must be 1..20000 and repeats must be 1..10")
    try:
        root = args.output_dir or ROOT / Path(load_config().output.dir).expanduser()
        if args.worker:
            result = worker(args.worker, output_directory(root), args.rows, args.mode, keep_workloads=args.keep_workloads)
            print(json.dumps(result, allow_nan=False))
            return 0
        report = run(root, rows=args.rows, repeats=args.repeats, jobs=args.jobs, mode=args.mode,
                     keep_workloads=args.keep_workloads)
        print(report)
        return 0 if json.loads(report.read_text())["status"] == "ok" else 1
    except KeyboardInterrupt:
        print("Benchmark cancelled; incomplete synthetic artifacts may remain under output.", file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError, ImportError, subprocess.TimeoutExpired):
        print("Benchmark failed. Check the output directory, dependencies and workload limits.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
