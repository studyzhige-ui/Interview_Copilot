"""Process-owned audio work. Cancelling a waiter never unlocks WhisperX early.

A single worker owns the mutable local model. Probe work has a separate bounded
pool. Prefork children discard inherited thread handles; shutdown stops new
admission while already-running work keeps its slot and accounting receipt.
"""

import os
from threading import Lock
from app.core.bounded_work import BoundedWorkPool, WorkCapacityExceeded

_lock = Lock()
_pools = {}
_closed = False


def _after_fork():
    global _lock, _pools, _closed
    _lock, _pools, _closed = Lock(), {}, False


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def pool(kind):
    if kind not in {"local", "probe"}:
        raise ValueError("unknown_audio_worker")
    with _lock:
        if _closed:
            raise WorkCapacityExceeded("audio: shutting down")
        if kind not in _pools:
            _pools[kind] = BoundedWorkPool(
                f"audio-{kind}", workers=1 if kind == "local" else 2, queue_size=4
            )
        return _pools[kind]


def close_pools():
    global _closed
    with _lock:
        _closed = True
        old = list(_pools.values())
    for item in old:
        item.shutdown()


def open_pools():
    global _closed
    with _lock:
        if not _closed:
            return
        if any(item.snapshot()["inflight"] for item in _pools.values()):
            raise RuntimeError("previous audio workers have not drained")
        _pools.clear()
        _closed = False
