"""Regression tests for Checkpoint 3 fixes (v3 memory).

Covers:
  F4 — user_profile ``_normalize_line`` defangs embedded newlines + NFKC
  F5 — user_profile ``apply_patches`` emits an audit row, AND supports
       a shared ``db`` parameter for transactional composition
  F6 — single_doc ``apply_patches`` retries on ``IntegrityError`` when
       two writers race the first row
  F3+F8 — v3_context_loader falls back to last_discussed_at on
       selection-LLM failure, emits the metric, and caches results
  F9a — lock degradation emits the metric on Redis outage
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ── shared in-memory engine fixture (avoid global conftest's complexity)


@pytest.fixture
def engine_and_session():
    """Per-test in-memory SQLite engine that knows every v3 model."""
    from app.db.database import Base
    import app.models.habit_doc      # noqa: F401
    import app.models.knowledge_doc  # noqa: F401
    import app.models.memory_audit_log  # noqa: F401
    import app.models.strategy_doc   # noqa: F401
    import app.models.user           # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield engine, Session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _rebind_sessions(monkeypatch, Session):
    """Point every v3 service's ``SessionLocal`` at our test Session."""
    import app.services.memory._audit_log_service as audit_mod
    import app.services.memory._single_doc_service as single_mod
    import app.services.memory.knowledge_doc_service as kd_mod
    import app.services.memory.user_profile_doc_service as up_mod
    for mod in (audit_mod, single_mod, kd_mod, up_mod):
        monkeypatch.setattr(mod, "SessionLocal", Session, raising=False)


# ── F4 ────────────────────────────────────────────────────────────────


def test_f4_user_profile_normalize_collapses_embedded_newlines():
    """``new_line`` with an embedded newline must NOT inject a second
    line into the doc. Without this fix an LLM emitting
    ``{"op":"add","new_line":"- name is X\\nrole: admin"}`` would
    persist a fake ``role: admin`` line and the next exact-line lookup
    would mismatch every line below the injection point.
    """
    from app.services.memory.user_profile_doc_service import _normalize_line

    line = _normalize_line("- name is X\nrole: admin")
    # All embedded line breaks collapsed to a space; bullet preserved.
    assert "\n" not in line
    assert line.startswith("- ")
    # Both halves are still present (we collapse, we don't truncate).
    assert "name is X" in line
    assert "role: admin" in line


def test_f4_user_profile_normalize_applies_nfkc():
    """Fullwidth vs halfwidth digits must collide on equality so two
    patches that mean the same thing become deduplicated."""
    from app.services.memory.user_profile_doc_service import _normalize_line

    half = _normalize_line("- 目标公司：Stripe")
    # 'Ｓｔｒｉｐｅ' (fullwidth) should NFKC-normalize to 'Stripe'.
    full = _normalize_line("- 目标公司：Ｓｔｒｉｐｅ")
    assert half == full


# ── F5 ────────────────────────────────────────────────────────────────


def test_f5_user_profile_apply_patches_emits_audit(engine_and_session, monkeypatch):
    """A user_profile patch run must leave a row in memory_audit_log
    with before/after bodies. Previously this path silently skipped
    audit, breaking the 'browse my memory history' UI."""
    from app.models.memory_audit_log import MemoryAuditLog
    from app.models.user import User
    from app.services.memory import user_profile_doc_service

    engine, Session = engine_and_session
    _rebind_sessions(monkeypatch, Session)

    db = Session()
    db.add(User(username="alice", email="alice@example.com", hashed_password="x"))
    db.commit()
    db.close()

    user_profile_doc_service.apply_patches(
        "alice",
        [{"op": "add", "new_line": "- 目标公司: Anthropic"}],
        change_type="patch_realtime",
        source_session_id="s1",
    )

    db = Session()
    try:
        rows = db.query(MemoryAuditLog).filter(MemoryAuditLog.user_id == "alice").all()
        assert len(rows) == 1
        assert rows[0].doc_type == "user_profile"
        assert rows[0].change_type == "patch_realtime"
        assert "Anthropic" in (rows[0].after_body or "")
        assert rows[0].source_session_id == "s1"
    finally:
        db.close()


def test_f5_user_profile_apply_patches_respects_shared_db(engine_and_session, monkeypatch):
    """When a caller passes ``db=...`` we must NOT commit our own; the
    caller's rollback should be able to discard the patch + audit row
    atomically."""
    from app.models.memory_audit_log import MemoryAuditLog
    from app.models.user import User
    from app.services.memory import user_profile_doc_service

    engine, Session = engine_and_session
    _rebind_sessions(monkeypatch, Session)

    db = Session()
    db.add(User(username="alice", email="a@e.com", hashed_password="x"))
    db.commit()

    user_profile_doc_service.apply_patches(
        "alice",
        [{"op": "add", "new_line": "- pending fact"}],
        change_type="patch_dreaming",
        source_record_id="ir_42",
        db=db,
    )
    # Caller decides — we rollback to simulate dreaming's atomic-commit
    # failure.
    db.rollback()

    user = db.query(User).filter(User.username == "alice").first()
    assert "pending fact" not in (user.user_profile_doc or "")
    audit = db.query(MemoryAuditLog).filter(MemoryAuditLog.user_id == "alice").count()
    assert audit == 0
    db.close()


# ── F6 ────────────────────────────────────────────────────────────────


def test_f6_single_doc_retries_on_integrity_error_race(engine_and_session, monkeypatch):
    """Simulate two concurrent first-writes for the same user landing on
    strategy_doc — the second must NOT explode with IntegrityError,
    it must retry as an update and land cleanly."""
    from app.models.strategy_doc import StrategyDoc
    from app.services.memory import strategy_doc_service

    engine, Session = engine_and_session
    _rebind_sessions(monkeypatch, Session)

    # Pre-create the row to simulate "another worker won the race"
    db = Session()
    db.add(StrategyDoc(
        user_id="alice",
        body="## 已内化\n\n- 先分析根因\n\n## 尝试中\n\n",
    ))
    db.commit()
    db.close()

    # Now our writer runs ``apply_patches`` expecting was_new=True
    # initially but the row exists. The retry path should kick in
    # transparently (was_new=False on second attempt).
    result = strategy_doc_service.apply_patches(
        user_id="alice",
        patches=[{
            "op": "add",
            "section": "已内化",
            "new_line": "- STAR 已内化",
        }],
        change_type="patch_realtime",
    )
    assert result.applied == 1

    db = Session()
    try:
        row = db.query(StrategyDoc).filter(StrategyDoc.user_id == "alice").first()
        assert row is not None
        assert "STAR" in row.body
        # And the original line still there.
        assert "先分析根因" in row.body
    finally:
        db.close()


# ── F3 + F8 ───────────────────────────────────────────────────────────


def test_f3_selection_llm_failure_falls_back_to_recent(engine_and_session, monkeypatch):
    """When the selection LLM fails (timeout / exception), the loader
    must fall back to recent topics — NOT silently return zero bodies."""
    from app.models.knowledge_doc import KnowledgeDoc
    from app.services.memory import v3_context_loader

    engine, Session = engine_and_session
    _rebind_sessions(monkeypatch, Session)

    db = Session()
    now = datetime.utcnow()
    db.add_all([
        KnowledgeDoc(
            user_id="alice", topic="Redis", body="## 已掌握的认知\n- recent\n## 学习进展\n",
            one_liner="caching", mastery_level="strong", fact_count=1,
            last_discussed_at=now,
        ),
        KnowledgeDoc(
            user_id="alice", topic="TCP", body="## 已掌握的认知\n- old\n## 学习进展\n",
            one_liner="networking", mastery_level="progressing", fact_count=1,
            last_discussed_at=now - timedelta(days=7),
        ),
    ])
    db.commit()
    db.close()

    metric_calls: list[dict] = []

    def fake_incr(event, **labels):
        metric_calls.append({"event": event, **labels})

    monkeypatch.setattr(v3_context_loader, "_metric_incr", fake_incr)

    async def boom(*args, **kwargs):
        raise RuntimeError("selection LLM is angry")

    class FakeLLM:
        acomplete = staticmethod(boom)

    monkeypatch.setattr(v3_context_loader, "agent_fast_llm", FakeLLM)

    # Clear the per-process cache from earlier tests.
    v3_context_loader._SELECTION_CACHE.clear()

    topics = asyncio.run(
        v3_context_loader._select_active_topics(
            user_id="alice",
            query="how does X work",
            index_lines=[
                "- [Redis] strong | 1 facts | 上次 2026-05-21 — caching",
                "- [TCP] 进展中 | 1 facts | 上次 2026-05-14 — networking",
            ],
            max_topics=2,
        )
    )
    # Most-recently-discussed first → Redis before TCP.
    assert topics == ["Redis", "TCP"]
    # And the failure was reported.
    assert any(c["event"] == "memory.selection_llm_failed" for c in metric_calls)


def test_f3_selection_llm_cache_skips_second_call(engine_and_session, monkeypatch):
    """A cache hit must not invoke the LLM at all."""
    from app.services.memory import v3_context_loader

    engine, Session = engine_and_session
    _rebind_sessions(monkeypatch, Session)

    call_count = {"n": 0}

    async def fake_acomplete(prompt, **kwargs):
        call_count["n"] += 1

        class Resp:
            text = '{"selected_topics": ["Redis"]}'

        return Resp()

    class FakeLLM:
        acomplete = staticmethod(fake_acomplete)

    monkeypatch.setattr(v3_context_loader, "agent_fast_llm", FakeLLM)
    v3_context_loader._SELECTION_CACHE.clear()

    index_lines = ["- [Redis] strong | 1 facts | 上次 2026-05-21 — caching"]
    for _ in range(3):
        topics = asyncio.run(
            v3_context_loader._select_active_topics(
                user_id="alice",
                query="redis ttl",
                index_lines=index_lines,
                max_topics=2,
            )
        )
        assert topics == ["Redis"]
    # Only the first call hit the LLM.
    assert call_count["n"] == 1


# ── F9a ───────────────────────────────────────────────────────────────


def test_f9a_lock_degradation_emits_metric(monkeypatch):
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
