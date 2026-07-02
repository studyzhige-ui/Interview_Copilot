"""Per-user memory-lock degradation test.

Preserved from the retired ``test_memory_checkpoint3.py``. That file's other
subjects — the deleted single-doc service's normaliser / audit / retry — were
re-ported onto the v3 surface in ``test_doc_patch_protocol.py`` (normaliser +
patch protocol) and ``test_memory_v3_schema.py`` (shared-db rollback +
IntegrityError retry), not dropped. The lock module ``_user_memory_lock`` is
unchanged by the v3 cutover, so this behaviour still matters: a Redis outage
must degrade the lock to a no-op AND emit the ``memory.lock_degraded`` metric so
ops can alarm on contention.
"""
from __future__ import annotations

import asyncio


def test_lock_degradation_emits_metric(monkeypatch):
    """When Redis is down the lock degrades silently and emits the
    ``memory.lock_degraded`` event so ops can alarm on contention."""
    from app.services.memory import _user_memory_lock as lock_mod

    captured: list[dict] = []
    monkeypatch.setattr(
        lock_mod, "_metric_incr",
        lambda event, **labels: captured.append({"event": event, **labels}),
    )

    class FakeRedis:
        async def set(self, *a, **kw):
            raise RuntimeError("connection refused")

        async def eval(self, *a, **kw):
            return 0

    monkeypatch.setattr(lock_mod, "redis_client", FakeRedis())

    async def run():
        async with lock_mod.user_memory_lock("alice"):
            pass

    asyncio.run(run())
    assert any(
        c["event"] == "memory.lock_degraded" and c["reason"] == "redis_down"
        for c in captured
    )
