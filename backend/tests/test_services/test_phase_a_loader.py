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
    import app.services.memory._db_helpers as helpers_mod
    import app.services.memory._single_doc_service as single_mod
    import app.services.memory.knowledge_doc_service as kd_mod
    import app.services.memory.user_profile_doc_service as up_mod
    # Includes ``_db_helpers`` because the doc services now route all
    # ``SessionLocal()`` opens through ``_db_helpers.session_scope`` —
    # rebinding only the doc-service modules' own ``SessionLocal``
    # leaves the helper's binding pointed at the real configured DB.
    for mod in (audit_mod, helpers_mod, single_mod, kd_mod, up_mod):
        monkeypatch.setattr(mod, "SessionLocal", Session, raising=False)


# ── single_doc one_liner derivation ───────────────────────────────────


def test_load_all_accepts_db_kwarg(engine_and_session, monkeypatch):
    """``knowledge_doc_service.load_all`` must accept ``db: Session |
    None`` so the ``/memory/overview`` endpoint (and any future
    orchestrator) can share one session across all four memory reads.
    Before P1-J this function was the only doc-service reader without
    the kwarg.
    """
    from app.services.memory import knowledge_doc_service

    _, Session = engine_and_session
    _rebind(monkeypatch, Session)

    # Without db: helper opens + closes a fresh session internally.
    rows = knowledge_doc_service.load_all("alice")
    assert rows == []

    # With db: shared session, helper doesn't close it.
    shared = Session()
    try:
        rows2 = knowledge_doc_service.load_all("alice", db=shared)
        assert rows2 == []
        # Session is still usable after the call.
        assert shared.is_active
    finally:
        shared.close()


def test_load_universal_opens_exactly_one_db_session(engine_and_session, monkeypatch):
    """``load_universal`` MUST share a single ``SessionLocal()`` across
    all four universal-pass reads (user_profile + knowledge_index +
    strategy_description + habit_description). Pre-fix each service
    opened its own — 4 connections per turn just for the universal
    pass, scaling worse in ``attach_active_bodies``.

    Counts every ``SessionLocal()`` invocation via a wrapper and
    asserts exactly 1 — a regression that reverts the plumbing would
    bump the count back to 4 and fail loudly.
    """
    from app.services.memory import (
        habit_doc_service, knowledge_doc_service,
        strategy_doc_service, user_profile_doc_service,
        v3_context_loader,
    )

    _, Session = engine_and_session
    _rebind(monkeypatch, Session)

    call_count = {"n": 0}
    real_session = Session

    def _counting_factory(*args, **kwargs):
        call_count["n"] += 1
        return real_session(*args, **kwargs)

    # Patch the helper's binding (and every doc service's, just to be
    # safe — the helper is the only consumer post P1-F, but if a
    # future change reverts to per-service opens we want the count
    # invariant to catch it).
    import app.services.memory._db_helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "SessionLocal", _counting_factory)
    monkeypatch.setattr(user_profile_doc_service, "SessionLocal", _counting_factory)
    monkeypatch.setattr(knowledge_doc_service, "SessionLocal", _counting_factory)
    import app.services.memory._single_doc_service as single_mod
    monkeypatch.setattr(single_mod, "SessionLocal", _counting_factory)

    v3_context_loader.load_universal("alice")

    # Acceptable upper bound: 1 (the goal). Strictly assert it.
    assert call_count["n"] == 1, (
        f"load_universal should open EXACTLY 1 SessionLocal across "
        f"its 4 service calls; got {call_count['n']}. A regression "
        f"that drops the shared-session plumbing brings this back "
        f"to 4 — silently regressing perf without breaking behavior."
    )


def test_memory_overview_opens_exactly_one_db_session(engine_and_session, monkeypatch):
    """``/memory/overview`` endpoint MUST share a single ``SessionLocal()``
    across its 4 doc-service reads (user_profile + knowledge.load_all
    + strategy + habit). Pre-P1-J each opened its own — 4 connections
    per page load for the user-facing endpoint, mirroring the agent
    side's pre-P1-F behavior.

    Same counter pattern as
    ``test_load_universal_opens_exactly_one_db_session``: a future
    refactor that drops ``db=db`` from any of the 4 calls bumps the
    counter back to 4 and this test fails loudly.
    """
    from app.api.chat.memory import memory_overview
    from app.services.memory import (
        habit_doc_service, knowledge_doc_service,
        strategy_doc_service, user_profile_doc_service,
    )

    _, Session = engine_and_session
    _rebind(monkeypatch, Session)

    call_count = {"n": 0}
    real_session = Session

    def _counting_factory(*args, **kwargs):
        call_count["n"] += 1
        return real_session(*args, **kwargs)

    import app.services.memory._db_helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "SessionLocal", _counting_factory)
    monkeypatch.setattr(user_profile_doc_service, "SessionLocal", _counting_factory)
    monkeypatch.setattr(knowledge_doc_service, "SessionLocal", _counting_factory)
    import app.services.memory._single_doc_service as single_mod
    monkeypatch.setattr(single_mod, "SessionLocal", _counting_factory)

    # Fake current_user — the endpoint only reads ``.username``.
    class _FakeUser:
        username = "alice"

    memory_overview(current_user=_FakeUser())

    assert call_count["n"] == 1, (
        f"/memory/overview should open EXACTLY 1 SessionLocal across "
        f"its 4 service calls; got {call_count['n']}. A regression "
        f"that drops ``db=db`` from any call would bring this back to "
        f"4 — silently regressing the user-facing perf gain from P1-J."
    )


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


# ── attach_active_bodies honours explicit planner decisions ──────────


def test_attach_active_bodies_loads_strategy_when_asked(engine_and_session, monkeypatch):
    """When the planner explicitly says load_strategy=True, the
    strategy body must end up in active_strategy_body. After the
    planner-merge refactor this is deterministic — no LLM call inside
    the loader."""
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

    ctx = v3_context_loader.load_universal("alice")
    ctx = asyncio.run(v3_context_loader.attach_active_bodies(
        ctx,
        user_id="alice",
        topics=[],
        load_strategy=True,
        load_habit=False,
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


# ── L1: index format ↔ extractor round-trip ──────────────────────────


def test_list_index_lines_round_trips_through_extract_topic_name(engine_and_session, monkeypatch):
    """``query_planner._extract_topic_names`` parses topic names out of
    ``knowledge_doc_service.list_index_lines`` output. The two are
    silently coupled by string format — if either drifts, the planner
    would silently reject every topic the LLM suggested (``t in
    valid_topics`` would always fail). Lock the contract with a
    round-trip test (originally review L1, kept after the planner
    merge moved the extractor).
    """
    from app.models.knowledge_doc import KnowledgeDoc
    from app.conversation.query_planner import _extract_topic_names
    from app.services.memory import knowledge_doc_service

    engine, Session = engine_and_session
    _rebind(monkeypatch, Session)

    # Seed three topics with varying mastery + dates so the format
    # exercises all conditional branches in list_index_lines.
    from datetime import datetime
    db = Session()
    try:
        db.add_all([
            KnowledgeDoc(
                user_id="alice", topic="Redis", body="## 已掌握的认知\n- x\n",
                one_liner="caching", mastery_level="strong", fact_count=8,
                last_discussed_at=datetime(2026, 5, 21),
            ),
            KnowledgeDoc(
                user_id="alice", topic="Postgres", body="## 已掌握的认知\n- y\n",
                one_liner="networking", mastery_level="progressing", fact_count=3,
                last_discussed_at=None,
            ),
            KnowledgeDoc(
                user_id="alice", topic="系统设计", body="## 已掌握的认知\n- z\n",
                one_liner="", mastery_level=None, fact_count=1,
                last_discussed_at=datetime(2026, 4, 10),
            ),
        ])
        db.commit()
    finally:
        db.close()

    lines = knowledge_doc_service.list_index_lines("alice", max_topics=10)
    assert len(lines) == 3
    extracted = _extract_topic_names(lines)
    # Every produced line MUST yield a topic name, and the round-trip
    # set must match what we put in.
    assert len(extracted) == 3, (
        f"Some index lines didn't round-trip: {list(zip(lines, extracted))}"
    )
    assert set(extracted) == {"Redis", "Postgres", "系统设计"}
