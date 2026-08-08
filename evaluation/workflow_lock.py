"""Cross-process locks for mutable evaluation infrastructure."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_ROOT = PROJECT_ROOT / "data" / "evaluation" / "locks"


@contextmanager
def evaluation_index_lock():
    """Prevent index rebuilds from overlapping quality or latency measurements."""
    from filelock import FileLock, Timeout

    LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(LOCK_ROOT / "index-workflow.lock"))
    try:
        with lock.acquire(timeout=0):
            yield
    except Timeout as exc:
        raise RuntimeError(
            "Another evaluation index build or benchmark is already running"
        ) from exc


__all__ = ["evaluation_index_lock"]
