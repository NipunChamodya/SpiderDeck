"""Read-only summaries of private collection audits; never follows linked files."""
from __future__ import annotations

import heapq
import json
import os
import re
import stat
from pathlib import Path
from typing import Iterator

from security.filesystem import check_owned_file, open_output_directory, verify_directory
from security.network_policy import origin
from security.validators import UnsafePathError
from ui import menu
from ui.display import options, terminal_text

_NAME = re.compile(r"crawl-audit-[0-9a-f]{32}\.json\Z")
_CODE = re.compile(r"[a-z_]{1,80}\Z")


def show_summaries(root: Path) -> None:
    if root.is_symlink():
        raise UnsafePathError("Output directory must not be a symlink.")
    if not root.exists():
        print("No collection audits found.")
        return
    root = root.resolve()
    with open_output_directory(root) as directory_fd:
        def candidates() -> Iterator[tuple[int, str]]:
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if _NAME.fullmatch(entry.name):
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode):
                            yield info.st_mtime_ns, entry.name
        newest = heapq.nlargest(20, candidates())
        if not newest:
            print("No collection audits found.")
            return
        print("Collection audit summaries (up to 20 newest; no document contents)")
        unreadable = 0
        for _, name in newest:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                with os.fdopen(fd, "rb") as handle:
                    check_owned_file(handle.fileno())
                    if os.fstat(handle.fileno()).st_size > 65536:
                        raise ValueError
                    data = handle.read(65537)
                    if len(data) > 65536:
                        raise ValueError
                payload = json.loads(data)
                target, outcome = payload["origin"], payload["stop_reason"]
                if target != origin(target) or not _CODE.fullmatch(outcome):
                    raise ValueError
                counts = [payload[key] for key in ("pages_collected", "records_collected", "records_saved", "requests")]
                if any(type(value) is not int or not 0 <= value <= 10**12 for value in counts):
                    raise ValueError
                print(f"{name}: {terminal_text(target, 300)} | {outcome}")
                print(f"  Pages: {counts[0]}; records collected/saved: {counts[1]}/{counts[2]}; attempts: {counts[3]}")
            except (OSError, ValueError, KeyError, TypeError, RecursionError):
                unreadable += 1
        verify_directory(root, directory_fd)
        if unreadable:
            print(f"{unreadable} audit files could not be read safely (permissions, size or format).")


def run(root: Path) -> None:
    while True:
        action = menu.prompt_choice("Security and collection audit:", [
            "Run offline security self-check", "View collection audit summaries", "Back"])
        if action in {None, "Back"}:
            return
        if action == "Run offline security self-check":
            from security import selfcheck
            ok = selfcheck.run(verbose=not options().quiet, plain=options().plain)
            if options().quiet:
                print("Security self-check: " + ("PASS" if ok else "FAIL"))
        elif action == "View collection audit summaries":
            try:
                show_summaries(root)
            except (OSError, ValueError):
                print("Cannot inspect audits safely. Check output permissions and configuration.")
