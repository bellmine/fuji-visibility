"""Cross-process refresh lock used by the web process and snapshot worker."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


class RefreshBusyError(RuntimeError):
    """Raised when another process already owns the refresh lock."""


@contextmanager
def refresh_lock(path: str | Path) -> Iterator[TextIO]:
    lock_path = Path(path).expanduser()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RefreshBusyError("A forecast refresh is already running.") from exc
        yield handle
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
