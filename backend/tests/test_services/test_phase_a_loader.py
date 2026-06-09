"""v3 context-loader tests (``app.services.memory.v3_context_loader``).

The loader assembles the memory bundle injected into every chat turn:

  * ``load_universal``       — the cheap every-turn pass: user_profile FULL
                               body + active ability states (compact) +
                               learning_strategy one-liner.
  * ``attach_active_bodies`` — hydrates the full learning_strategy body only
                               when the planner asks (``load_strategy=True``).
  * ``V3MemoryContext.render`` — renders the bundle to markdown, omitting the
                               strategy *detail* section unless the body loaded.

The services open their own ``SessionLocal`` internally, so — like the other
v3 memory tests — we run on a dedicated in-memory engine and rebind every
service's ``SessionLocal`` to it, then seed a ``users`` row (the services
resolve a username → ``users.id``).
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
    import app.models.memory_ability_state  # noqa: F401
    import app.models.memory_audit_logs     # noqa: F401
    import app.models.memory_document       # noqa: F401
    import app.models.user                  # noqa: F401

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


@pytest.fixture
def seeded(engine_and_session, monkeypatch):
    """Rebind service SessionLocals to the test engine and seed one user.

    Rebinds ``_db_helpers`` too because ``load_universal`` /
    ``attach_active_bodies`` route their reads through
    ``_db_helpers.session_scope`` — rebinding only the doc/ability service
    modules would leave the helper's binding pointed at the real DB.
    """
    _engine, Session = engine_and_session
    import app.services.memory._db_helpers as helpers_mod
    import app.services.memory._memory_audit as audit_mod
    import app.services.memory.memory_ability_state_service as ability_mod
    import app.services.memory.memory_document_service as doc_mod
    for mod in (helpers_mod, audit_mod, ability_mod, doc_mod):
        monkeypatch.setattr(mod, "SessionLocal", Session, raising=False)

    from app.models.user import User
    s = Session()
    s.add(User(username="alice", hashed_password="x"))
    s.commit()
    s.close()
    return Session


# ── load_universal: user_profile body + ability states + strategy one-liner ─


def test_load_universal_returns_profile_abilities_and_strategy_oneliner(seeded):
    from app.services.memory import (
        memory_ability_state_service,
        memory_document_service,
        v3_context_loader,
    )

    memory_document_service.apply_patches(
        "alice", "user_profile",
        [{"op": "add", "new_line": "- 目标：后端岗位"}],
        change_type="patch_realtime",
    )
    memory_document_service.apply_patches(
        "alice", "learning_strategy",
        [{"op": "add", "new_line": "- 先讲思路再写代码"}],
        change_type="patch_realtime",
    )
    memory_ability_state_service.upsert(
        "alice", topic="Redis 缓存穿透", skill_type="knowledge_topic",
        mastery_level="weak", summary="不懂布隆过滤器", change_type="patch_realtime",
    )

    ctx = v3_context_loader.load_universal("alice")

    # user_profile is the FULL body.
    assert "后端岗位" in ctx.user_profile_body
    # ability states are compact per-topic dicts.
    assert len(ctx.ability_states) == 1
    state = ctx.ability_states[0]
    assert state["topic"] == "Redis 缓存穿透"
    assert state["skill_type"] == "knowledge_topic"
    assert state["mastery_level"] == "weak"
    assert state["summary"] == "不懂布隆过滤器"
    # learning_strategy is the one-liner ONLY, not the full body...
    assert ctx.learning_strategy_description
    assert "先讲思路" in ctx.learning_strategy_description
    # ...and the on-demand full body is NOT loaded by the universal pass.
    assert ctx.active_learning_strategy_body == ""


def test_load_universal_empty_for_user_with_no_memory(seeded):
    from app.services.memory import v3_context_loader

    ctx = v3_context_loader.load_universal("alice")
    assert ctx.user_profile_body == ""
    assert ctx.ability_states == []
    assert ctx.learning_strategy_description == ""
    assert ctx.active_learning_strategy_body == ""


# ── attach_active_bodies honours an explicit planner decision ────────────


def test_attach_active_bodies_loads_strategy_when_asked(seeded):
    """When the planner says load_strategy=True, the full learning_strategy
    body must end up in ``active_learning_strategy_body``. Deterministic —
    no LLM call inside the loader."""
    from app.services.memory import memory_document_service, v3_context_loader

    memory_document_service.apply_patches(
        "alice", "learning_strategy",
        [{"op": "add", "new_line": "- STAR 法已内化"}],
        change_type="patch_realtime",
    )

    ctx = v3_context_loader.load_universal("alice")
    assert ctx.active_learning_strategy_body == ""  # not loaded by universal pass

    ctx = asyncio.run(v3_context_loader.attach_active_bodies(
        ctx, user_id="alice", load_strategy=True,
    ))
    assert "STAR" in ctx.active_learning_strategy_body


def test_attach_active_bodies_skips_strategy_when_not_asked(seeded):
    """load_strategy=False (the default) must leave the body empty even when
    a learning_strategy doc exists."""
    from app.services.memory import memory_document_service, v3_context_loader

    memory_document_service.apply_patches(
        "alice", "learning_strategy",
        [{"op": "add", "new_line": "- 不该被加载的正文"}],
        change_type="patch_realtime",
    )

    ctx = v3_context_loader.load_universal("alice")
    ctx = asyncio.run(v3_context_loader.attach_active_bodies(
        ctx, user_id="alice", load_strategy=False,
    ))
    assert ctx.active_learning_strategy_body == ""


# ── render output reflects what's loaded ─────────────────────────────────


def test_render_includes_profile_abilities_and_strategy_oneliner():
    """render() shows the user_profile, the ability lines, and the strategy
    OVERVIEW (one-liner) — but NOT the strategy detail section when the full
    body wasn't loaded."""
    from app.services.memory.v3_context_loader import V3MemoryContext

    ctx = V3MemoryContext(
        user_profile_body="- 用户：alice",
        ability_states=[
            {"topic": "Redis", "skill_type": "knowledge_topic",
             "mastery_level": "weak", "summary": "穿透没搞懂"},
        ],
        learning_strategy_description="先分析根因",
        active_learning_strategy_body="",
    )
    out = ctx.render()
    assert "用户画像" in out
    assert "alice" in out
    # Ability line rendered with the mastery label (weak → 弱).
    assert "能力状态" in out
    assert "Redis" in out
    assert "弱" in out
    assert "穿透没搞懂" in out
    # Strategy OVERVIEW (one-liner) present...
    assert "学习策略概览" in out
    assert "先分析根因" in out
    # ...but the strategy DETAIL section is NOT, since the body wasn't loaded.
    assert "学习策略详情" not in out


def test_render_prefers_full_strategy_body_over_oneliner_when_loaded():
    """Once the full learning_strategy body is attached, render() must show
    the detail section (not just the overview one-liner)."""
    from app.services.memory.v3_context_loader import V3MemoryContext

    ctx = V3MemoryContext(
        user_profile_body="- 用户：alice",
        ability_states=[],
        learning_strategy_description="先分析根因",
        active_learning_strategy_body="- 先分析根因\n- 再给方案",
    )
    out = ctx.render()
    assert "学习策略详情" in out
    assert "再给方案" in out
    # When the full body is shown the overview header is suppressed.
    assert "学习策略概览" not in out


def test_render_omits_empty_sections():
    """An entirely empty context renders to an empty string (no stray
    headers)."""
    from app.services.memory.v3_context_loader import V3MemoryContext

    assert V3MemoryContext().render() == ""
