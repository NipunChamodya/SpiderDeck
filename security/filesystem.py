"""Owned output directories and atomic, no-overwrite file publication.

SQLite opens pathnames itself. Its directory must therefore be owned by the
current user and not writable by other users. Same-user hostile processes and
replacement of trusted ancestor directories are outside this boundary.
"""
from __future__ import annotations

import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO

from security.validators import UnsafePathError, safe_output_path


def output_directory(requested: str | Path) -> Path:
    path = Path(requested).expanduser().absolute()
    if path.is_symlink():
        raise UnsafePathError("The configured output directory must not be a symlink.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path.resolve()


def output_filename(name: str) -> str:
    # One directory level keeps SQLite sidecars and exports easy to secure.
    if (not name or name in {".", ".."} or Path(name).name != name
            or any(char in name for char in "\\/\x00") or name.startswith(".")
            or len(name.encode("utf-8")) > 180):
        raise UnsafePathError("Choose a filename without directories, traversal or a leading dot.")
    return name


@contextmanager
def open_output_directory(root: Path) -> Iterator[int]:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise UnsafePathError("Output directory must be owned by you and not writable by other users.")
        verify_directory(root, fd)
        yield fd
    finally:
        os.close(fd)


def verify_directory(root: Path, fd: int) -> None:
    current = root.stat(follow_symlinks=False)
    opened = os.fstat(fd)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise UnsafePathError("Output directory changed; retry with a stable directory.")


def check_owned_file(fd: int) -> None:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise UnsafePathError("Database and sidecars must be private, owned regular files without hardlinks.")


@contextmanager
def new_output_text(root: Path, filename: str) -> Iterator[TextIO]:
    """Publish a complete UTF-8 file atomically; never replace an existing name."""
    filename = output_filename(filename)
    safe_output_path(root, filename)
    with open_output_directory(root) as directory_fd:
        temporary = f".export-{uuid.uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                yield handle
                handle.flush()
                os.fsync(handle.fileno())
            verify_directory(root, directory_fd)
            # link() is an atomic create-if-absent, unlike rename()/replace().
            os.link(temporary, filename, src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=directory_fd)
