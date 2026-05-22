"""Phase A regression tests — strategy/habit description-only loading.

Verifies:
  * universal pass exposes ``strategy_description`` / ``habit_description``,
    NOT full bodies
  * selection LLM decisions for strategy/habit body load are honoured
  * single_doc service derives a non-empty one_liner from a populated body
  * V3MemoryContext.render() never includes a body the LLM didn't request
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine_and_session():
    from app.db.database import Base
    import app.models.habit_doc       # noqa: F401
    import app.models.knowledge_doc   # noqa: F401
    import app.models.memory_audit_log  # noqa: F401
    import app.models.strategy_doc    # noqa: F401
    import app.models.user            # noqa: F401

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


def _rebind(monkeypatch, Session):
    import app.services.memory._audit_log_service as audit_mod
    import app.services.memory._single_doc_service as single_mod
    import app.services.memory.knowledge_doc_service as kd_mod
    import app.services.memory.user_profile_doc_service as up_mod
    for mod in (audit_mod, single_mod, kd_mod, up_mod):
        monkeypatch.setattr(mod, "SessionLocal", Session, raising=False)


# ── single_doc one_liner derivation ───────────────────────────────────


def test_strategy_apply_patches_populates_one_liner(engine_and_session, monkeypatch):
    """A patch run that adds a real bullet must leave a non-empty
    one_liner on the row so universal pass has something to show."""
    from app.models.strategy_doc import StrategyDoc
    from app.services.memory import strategy_doc_service

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    result = strategy_doc_service.apply_patches(
        user_id="alice",
        patches=[{
            "op": "add",
            "section": "已内化",
            "new_line": "- 先分析根因后给方案",
        }],
        change_type="patch_realtime",
    )
    assert result.applied == 1

    db = Session()
    try:
        row = db.query(StrategyDoc).filter(StrategyDoc.user_id == "alice").first()
        assert row is not None
        assert row.one_liner            # non-empty
        assert "先分析根因后给方案" in row.one_liner
    finally:
        db.close()


def test_strategy_load_description_returns_one_liner_only(engine_and_session, monkeypatch):
    """``load_description`` must return the one_liner, NOT the full body."""
    from app.services.memory import strategy_doc_service

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    strategy_doc_service.apply_patches(
        user_id="alice",
        patches=[{"op": "add", "section": "已内化", "new_line": "- 先分析根因"}],
        change_type="patch_realtime",
    )
    desc = strategy_doc_service.load_description("alice")
    assert desc
    # The full body has "## 已内化" headers in it; description should NOT.
    assert "##" not in desc


# ── universal pass exposes descriptions, not bodies ──────────────────


def test_load_universal_no_strategy_or_habit_body(engine_and_session, monkeypatch):
    """Phase A: load_universal MUST NOT return strategy_body or
    habit_body fields (they were renamed to descriptions)."""
    from app.models.user import User
    from app.services.memory import (
        habit_doc_service, strategy_doc_service, v3_context_loader,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    db = Session()
    db.add(User(username="alice", email="a@e.com", hashed_password="x"))
    db.commit()
    db.close()

    strategy_doc_service.apply_patches(
        user_id="alice",
        patches=[{"op": "add", "section": "已内化", "new_line": "- 策略A"}],
        change_type="patch_realtime",
    )
    habit_doc_service.apply_patches(
        user_id="alice",
        patches=[{"op": "add", "section": "稳定的练习节奏", "new_line": "- 节奏B"}],
        change_type="patch_realtime",
    )

    ctx = v3_context_loader.load_universal("alice")
    # Description fields present:
    assert ctx.strategy_description
    assert ctx.habit_description
    # Active bodies NOT loaded by universal pass:
    assert ctx.active_strategy_body == ""
    assert ctx.active_habit_body == ""
    # And the old "*_body" attrs are gone:
    assert not hasattr(ctx, "strategy_body")
    assert not hasattr(ctx, "habit_body")


# ── selection LLM decides per-doc-type ───────────────────────────────


def test_load_with_active_bodies_honours_strategy_decision(engine_and_session, monkeypatch):
    """When selection LLM says load_strategy=true, the strategy body
    must end up in active_strategy_body."""
    from app.models.user import User
    from app.services.memory import (
        strategy_doc_service, habit_doc_service, v3_context_loader,
    )

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    db = Session()
    db.add(User(username="alice", email="a@e.com", hashed_password="x"))
    db.commit()
    db.close()

    strategy_doc_service.apply_patches(
        user_id="alice",
        patches=[{"op": "add", "section": "已内化", "new_line": "- STAR 法已内化"}],
        change_type="patch_realtime",
    )
    habit_doc_service.apply_patches(
        user_id="alice",
        patches=[{"op": "add", "section": "稳定的练习节奏", "new_line": "- 每周一三五"}],
        change_type="patch_realtime",
    )

    # Stub the selection LLM to say load strategy=true, habit=false.
    async def fake_acomplete(prompt, **kwargs):
        class Resp:
            text = (
                '{"knowledge_topics": [], '
                '"load_strategy": true, "load_habit": false}'
            )
        return Resp()

    class FakeLLM:
        acomplete = staticmethod(fake_acomplete)

    monkeypatch.setattr(v3_context_loader, "agent_fast_llm", FakeLLM)
    v3_context_loader._SELECTION_CACHE.clear()

    ctx = asyncio.run(v3_context_loader.load_with_active_bodies(
        "alice", query="how do I answer behavioural questions",
    ))
    assert "STAR" in ctx.active_strategy_body
    assert ctx.active_habit_body == ""


# ── render output reflects what's loaded ─────────────────────────────


def test_render_omits_body_sections_when_not_active(engine_and_session, monkeypatch):
    """Render must NOT print '# 答题策略详情' when active_strategy_body is empty."""
    from app.services.memory.v3_context_loader import V3MemoryContext

    ctx = V3MemoryContext(
        user_profile_body="- 用户：alice",
        strategy_description="2 条；首条：先分析根因",
        habit_description="",
        active_strategy_body="",
        active_habit_body="",
    )
    out = ctx.render()
    # Description block is in the universal pass:
    assert "答题策略 doc" in out
    # But the detail section is NOT, since the body wasn't loaded:
    assert "答题策略详情" not in out
    assert "学习习惯与心态详情" not in out
