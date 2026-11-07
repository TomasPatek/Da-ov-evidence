"""Atomic file writes and inter-process file locking."""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via temp file + fsync + rename so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            # Keep permissions of the file being replaced.
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    _fsync_dir(path.parent)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def lock_path_for(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive advisory lock guarding writes to ``path``.

    Uses a sidecar lock file because the data file itself is replaced on every write.
    ``flock`` locks belong to the open file description, so this also serialises
    threads within one process.
    """
    lock = lock_path_for(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+b") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
