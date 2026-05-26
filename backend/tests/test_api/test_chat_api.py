"""API tests for ``app.api.chat`` — session CRUD, transcript, history.

These exercise the router via FastAPI's TestClient with ``get_current_user``
and ``get_db`` overridden so we don't need a JWT or a real Postgres.

We construct a local in-memory SQLite engine inside the module because the
shared ``db_session`` fixture in ``tests/conftest.py`` references the missing
``app.models.interview`` module.
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.api import memory as memory_api
from app.api.chat import sessions as chat_sessions_mod
from app.core.security import get_current_user
from app.db.database import Base, get_db
import app.models  # noqa: F401  — ensure mappers registered
from app.models.chat import ChatMessage, ChatSession


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(monkeypatch) -> Iterator[Session]:
    # StaticPool + a single shared connection so the dependency-override
    # session and the test's own session see the same in-memory DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session_ = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # The v3 memory doc services (knowledge_doc / strategy_doc / habit_doc /
    # user_profile_doc / _single_doc / _audit_log) bypass FastAPI's
    # ``get_db`` and open their own session via ``SessionLocal()`` imported
    # at module-load time. To keep memory-endpoint tests honest we must
    # rebind every such reference to a sessionmaker that points at THIS
    # in-memory engine — otherwise those endpoints would talk to the real
    # configured database (or fail with "no such table: knowledge_docs").
    import app.services.memory._audit_log_service as _audit_mod
    import app.services.memory._db_helpers as _helpers_mod
    import app.services.memory._single_doc_service as _single_mod
    import app.services.memory.knowledge_doc_service as _kd_mod
    import app.services.memory.user_profile_doc_service as _up_mod
    # Includes ``_db_helpers`` because the doc services now route all
    # ``SessionLocal()`` opens through ``_db_helpers.session_scope`` —
    # rebinding only the doc-service modules' own ``SessionLocal``
    # leaves the helper's binding pointed at the real configured DB.
    for _mod in (_audit_mod, _helpers_mod, _single_mod, _kd_mod, _up_mod):
        monkeypatch.setattr(_mod, "SessionLocal", Session_, raising=False)

    session = Session_()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """A TestClient with dependency overrides for auth + DB."""
    class FakeUser:
        username = "alice"

    def fake_user() -> FakeUser:
        return FakeUser()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1")
    # /memory/* lives under app.api.memory now (moved out of chat/
    # in P8-1 because the routes are cross-session memory CRUD,
    # not chat-session operations). Mount it here so the existing
    # tests targeting ``/api/v1/memory/...`` keep working.
    app.include_router(memory_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield TestClient(app)


# ── /chat/sessions ────────────────────────────────────────────────────────


def test_create_chat_session_defaults_to_general(client: TestClient, db: Session):
    resp = client.post("/api/v1/chat/sessions", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_type"] == "general"
    assert body["title"] == "通用对话"
    # DB-side effect: row exists.
    row = db.query(ChatSession).filter(ChatSession.id == body["session_id"]).first()
    assert row is not None
    assert row.user_id == "alice"


def test_create_debrief_session_requires_existing_interview(client: TestClient):
    resp = client.post(
        "/api/v1/chat/sessions",
        json={"session_type": "debrief", "interview_id": "ir_missing"},
    )
    assert resp.status_code == 404


def test_list_chat_sessions_is_user_scoped(client: TestClient, db: Session):
    db.add_all([
        ChatSession(id="s_a", user_id="alice", title="A", session_type="general"),
        ChatSession(id="s_b", user_id="bob",   title="B", session_type="general"),
    ])
    db.commit()
    resp = client.get("/api/v1/chat/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert ids == ["s_a"]


def test_rename_session_validates_non_empty(client: TestClient, db: Session):
    db.add(ChatSession(id="s1", user_id="alice", title="old", session_type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "   "})
    assert resp.status_code == 400


def test_rename_session_updates_title(client: TestClient, db: Session):
    db.add(ChatSession(id="s1", user_id="alice", title="old", session_type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "new"})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(ChatSession,"s1").title == "new"


def test_rename_session_rejects_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="old", session_type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s_bob/title", json={"title": "new"})
    assert resp.status_code == 404


def test_delete_session_removes_row_and_messages(client: TestClient, db: Session):
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.add(ChatMessage(session_id="s1", seq=1, role="User", content="hi"))
    db.commit()
    resp = client.delete("/api/v1/chat/sessions/s1")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(ChatSession,"s1") is None
    assert db.query(ChatMessage).filter(ChatMessage.session_id == "s1").count() == 0


# ── /chat/history ─────────────────────────────────────────────────────────


def test_history_returns_in_seq_order(client: TestClient, db: Session):
    # 0018 reverted the conversation_id split — messages are scoped only
    # by session_id again.
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.add(ChatMessage(session_id="s1", seq=1, role="User", content="hi"))
    db.add(ChatMessage(session_id="s1", seq=2, role="AI", content="hello"))
    db.commit()
    resp = client.get("/api/v1/chat/history", params={"session_id": "s1"})
    assert resp.status_code == 200
    seqs = [m["seq"] for m in resp.json()]
    assert seqs == [1, 2]


def test_history_404_for_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="t", session_type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/history", params={"session_id": "s_bob"})
    assert resp.status_code == 404


# ── /chat/transcript ──────────────────────────────────────────────────────


def test_transcript_returns_structured_state(client: TestClient, db: Session, monkeypatch):
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="debrief"))
    db.commit()

    class FakeTranscriptSvc:
        @staticmethod
        def get_session_meta(session_id):
            return {
                "turn_count": 2,
                "compaction_cursor": 4,
                "session_state": '{"mode": "debrief", "summary": "focus on redis"}',
                "session_type": "debrief",
                "current_conversation_id": "s1",
            }

        @staticmethod
        def get_full_transcript(session_id, conversation_id=None):
            # The real signature picked up a ``conversation_id`` kwarg in
            # migration 0015; the handler always passes it through (even
            # when None) so the fake must accept it.
            return [{"seq": 1, "role": "User", "content": "hi", "created_at": "t"}]

    monkeypatch.setattr(chat_sessions_mod, "transcript_service", FakeTranscriptSvc)
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_type"] == "debrief"
    assert body["compaction_cursor"] == 4
    assert body["session_state"]["summary"] == "focus on redis"
    assert body["total_messages"] == 1


def test_transcript_404_for_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="t", session_type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s_bob"})
    assert resp.status_code == 404


# ── /memory/* (v3) ────────────────────────────────────────────────────────


def test_memory_overview_returns_v3_bundle(client: TestClient):
    """Smoke: /memory/overview returns the 4-doc bundle (empty for a
    user with no memory yet)."""
    resp = client.get("/api/v1/memory/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "user_profile_body" in body
    assert "knowledge_topics" in body
    assert "strategy_body" in body
    assert "habit_body" in body
    # Fresh user → empty topic list (not None / missing).
    assert isinstance(body["knowledge_topics"], list)


def test_memory_knowledge_topic_get_404_when_missing(client: TestClient):
    resp = client.get("/api/v1/memory/knowledge/topics/does_not_exist")
    assert resp.status_code == 404


# ── /chat/sse — streaming (smoke test) ────────────────────────────────────


def test_sse_chat_endpoint_streams_chunks(client: TestClient, db: Session, monkeypatch):
    """Smoke test for the SSE pipeline: dependency-overridden user owns the
    session, the engine yields HarnessEvent text_delta + done, and the
    response is an SSE stream terminated with ``"type": "done"``."""
    db.add(ChatSession(id="s1", user_id="alice", title="t", session_type="general"))
    db.commit()

    async def fake_submit(self):
        from app.conversation.events import HarnessEvent
        yield HarnessEvent.text_delta("hello ", step=0, elapsed_ms=0)
        yield HarnessEvent.text_delta("world", step=0, elapsed_ms=0)
        yield HarnessEvent.text("hello world", step=0, elapsed_ms=0)
        yield HarnessEvent.done(step=0, elapsed_ms=0)

    # The Stage-G SSE endpoint constructs a ConversationEngine and
    # iterates its submit_message generator. Patch the method
    # directly so we don't need to wire the planner / retrieval /
    # memory subsystems in the unit test.
    from app.conversation.engine import ConversationEngine
    monkeypatch.setattr(ConversationEngine, "submit_message", fake_submit)

    resp = client.post("/api/v1/chat/sse/s1", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.text
    assert "hello" in body and "world" in body
    assert '"type": "done"' in body


def test_mock_start_resume_tier_order(client: TestClient, db: Session, monkeypatch):
    """``start_mock_interview`` tries three resume-resolution tiers
    in a load-bearing order: ``resume_sections`` (structured) →
    ``KnowledgeDocument`` docstore (chunks already parsed at library-
    upload time) → ``_parse_resume_on_demand`` (last-resort S3 +
    LlamaParse, ~8s). A future contributor swapping that order would
    silently regress mock_start latency (or quality).

    This test wires a call-recorder into each tier and drives three
    scenarios; the recorder asserts both WHICH tiers ran AND in WHAT
    ORDER. Pre-fix the wiring was "verified by hand" per the comment
    in mock_interview.py.
    """
    import json as _json

    # Owning session + UserUpload row (the endpoint validates both).
    db.add(ChatSession(
        id="s_mock", user_id="alice", title="模拟面试",
        session_type="mock_interview",
    ))
    from app.models.upload import UserUpload
    db.add(UserUpload(
        id="upl_resume", user_id="alice",
        original_filename="r.pdf",
        storage_uri="s3://bucket/r.pdf",
        object_key="r.pdf",
        purpose="knowledge_document",
        status="ready",
    ))
    db.commit()

    calls: list[str] = []

    # Stub each tier so we can assert ordering without paying their
    # real cost.
    def fake_sections(upload_id, user_id):
        calls.append("sections")
        return []  # forces tier 2/3

    def fake_format(sections, **kw):
        return "(formatted) " + " ".join(s.title for s in sections)

    def fake_find_kdoc(db_, upload_id, user_id):
        calls.append("find_kdoc")
        # ``has_kdoc`` driven by scenario below.
        return _fake_kdoc[0]

    def fake_docstore_read(doc, **k):
        calls.append("docstore")
        return ("docstore text", 3)

    async def fake_reparse(db_, upload_id, user_id):
        calls.append("reparse")
        return "reparsed text"

    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_upload",
        fake_sections,
    )
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.format_for_context",
        fake_format,
    )
    monkeypatch.setattr(
        "app.services.knowledge.knowledge_text_service.find_knowledge_doc_by_upload",
        fake_find_kdoc,
    )
    monkeypatch.setattr(
        "app.services.knowledge.knowledge_text_service.read_full_text_from_docstore",
        fake_docstore_read,
    )
    monkeypatch.setattr(
        "app.api.chat.mock_interview._parse_resume_on_demand",
        fake_reparse,
    )

    # Stub generate_brief so the endpoint doesn't make a real LLM call.
    from app.services.interview.mock_interview_service import InterviewBrief
    fake_brief = InterviewBrief(
        interview_plan={"phases": [
            {"phase": "self_intro", "budget": 1, "goal": "x",
             "suggested_topics": [], "difficulty": "warm_up"},
        ]},
        opening_spoken="你好",
        opening_question="请简单做个自我介绍",
        min_turns=3, target_turns=5, max_turns=8,
    )
    async def fake_generate_brief(**kwargs):
        return fake_brief
    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_brief",
        fake_generate_brief,
    )
    # build_prefix / prefix_hash are deterministic pure functions —
    # let them run for real; they don't hit external services.

    # ── Scenario A: sections-tier hit (no kdoc lookup, no reparse) ──
    _fake_kdoc = [None]  # sentinel — not consulted in scenario A
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_upload",
        lambda u, n: (calls.append("sections"), [
            # Non-empty so tier 1 wins.
            type("S", (), {"section_type": "summary", "title": "X", "content": "y"})()
        ])[1],
    )
    resp = client.post(
        "/api/v1/chat/mock-interview/start",
        json={
            "session_id": "s_mock",
            "resume_upload_id": "upl_resume",
            "jd_text": "JD content",
            "interviewer_style": "professional",
            "voice_mode": "hybrid",
        },
    )
    assert resp.status_code == 200, resp.text
    assert calls == ["sections"], (
        f"sections tier should be the only one consulted when "
        f"resume_sections is non-empty; got calls={calls}"
    )

    # ── Scenario B: sections empty + kdoc present → docstore wins ──
    calls.clear()
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_upload",
        fake_sections,  # returns []
    )

    class _FakeKDoc:
        id = "kdoc_X"
        title = "resume.pdf"
        status = "ready"
        node_ids = _json.dumps(["n1", "n2"])
        created_at = None

    _fake_kdoc[0] = _FakeKDoc()
    # Reset session_state since the first scenario already initialized.
    s = db.query(ChatSession).filter(ChatSession.id == "s_mock").first()
    s.session_state = None
    db.commit()

    resp = client.post(
        "/api/v1/chat/mock-interview/start",
        json={
            "session_id": "s_mock",
            "resume_upload_id": "upl_resume",
            "jd_text": "JD content",
            "interviewer_style": "professional",
            "voice_mode": "hybrid",
        },
    )
    assert resp.status_code == 200, resp.text
    # Sections checked first, fails → docstore tier consulted and wins.
    # ``reparse`` must NOT be called (that's the whole point of the
    # docstore tier — it saved the 8-second LlamaParse round-trip).
    assert "sections" in calls and "find_kdoc" in calls and "docstore" in calls, (
        f"expected sections+find_kdoc+docstore to all be consulted; "
        f"got calls={calls}"
    )
    assert "reparse" not in calls, (
        f"reparse tier ran even though docstore returned text; "
        f"the perf optimization is silently broken. calls={calls}"
    )
    # Order check: sections BEFORE find_kdoc BEFORE docstore (load-
    # bearing tier priority — parsed/cleaned > raw chunks > re-parse).
    assert calls.index("sections") < calls.index("find_kdoc") < calls.index("docstore")

    # ── Scenario C: nothing → reparse fallback ──
    calls.clear()
    _fake_kdoc[0] = None  # no library doc either
    s = db.query(ChatSession).filter(ChatSession.id == "s_mock").first()
    s.session_state = None
    db.commit()

    resp = client.post(
        "/api/v1/chat/mock-interview/start",
        json={
            "session_id": "s_mock",
            "resume_upload_id": "upl_resume",
            "jd_text": "JD content",
            "interviewer_style": "professional",
            "voice_mode": "hybrid",
        },
    )
    assert resp.status_code == 200, resp.text
    # All three tiers consulted in order; reparse is the only one
    # that produces output.
    assert "sections" in calls
    assert "find_kdoc" in calls
    assert "reparse" in calls
    assert calls.index("sections") < calls.index("find_kdoc") < calls.index("reparse")


def test_in_progress_keeps_session_when_brief_launched_but_zero_qa(
    client: TestClient, db: Session,
):
    """Pre-fix sweeper bug: ``qa_history=[]`` was treated as "stale
    shell" and hard-deleted. But a user who started a mock and saw the
    AI's opening question without answering yet ALSO has
    ``qa_history=[]`` — and that session was being purged out from
    under them. Switching tabs mid-opening lost the whole interview.

    Post-fix: a session is only "stale" when the brief was NEVER
    launched (no ``interview_plan`` and no ``pending_question``).
    Sessions with a launched brief but no answers yet are PRESERVED
    and surfaced via the resume banner.
    """
    import json

    # Launched session: brief has run, opening question is sitting in
    # state, user has NOT answered yet.
    db.add(ChatSession(
        id="s_launched",
        user_id="alice",
        title="模拟面试",
        session_type="mock_interview",
        session_state=json.dumps({
            "schema_version": 2,
            "interview_plan": {
                "phases": [{"phase": "self_intro", "budget": 1, "goal": "x"}],
            },
            "pending_question": "先简单做个自我介绍吧",
            "qa_history": [],
            "is_finished": False,
        }),
    ))
    db.commit()

    resp = client.get("/api/v1/chat/mock-interview/in-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_in_progress"] is True, (
        "session with launched brief but zero Q&A must be surfaced as "
        "in-progress; pre-fix it was being silently hard-deleted"
    )
    assert body["session_id"] == "s_launched"
    assert body["qa_count"] == 0

    # The session row must still exist (the sweeper must NOT have
    # deleted it just because qa_history was empty).
    still_there = db.query(ChatSession).filter(ChatSession.id == "s_launched").first()
    assert still_there is not None


def test_in_progress_still_purges_genuine_stale_shells(
    client: TestClient, db: Session,
):
    """The "stale shell" purge has to stay alive for the originally
    intended case: a session row that was created but never reached
    brief-generation (plan LLM crashed, tab closed mid-startup). Those
    rows have neither ``interview_plan`` nor ``pending_question`` —
    truly empty shells, nothing for the user to resume.
    """
    import json

    db.add(ChatSession(
        id="s_shell",
        user_id="alice",
        title="模拟面试",
        session_type="mock_interview",
        # No interview_plan, no pending_question, no qa_history — the
        # session got created by /chat/sessions but the subsequent
        # /chat/mock-interview/start call never completed.
        session_state=json.dumps({"schema_version": 2}),
    ))
    db.commit()

    resp = client.get("/api/v1/chat/mock-interview/in-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_in_progress"] is False

    # Confirm the genuinely-empty shell IS hard-deleted (so it doesn't
    # keep haunting the resume banner on every page load).
    purged = db.query(ChatSession).filter(ChatSession.id == "s_shell").first()
    assert purged is None


def test_sse_chat_404_for_other_user(client: TestClient, db: Session):
    db.add(ChatSession(id="s_bob", user_id="bob", title="t", session_type="general"))
    db.commit()
    resp = client.post("/api/v1/chat/sse/s_bob", json={"message": "hi"})
    assert resp.status_code == 404


def test_sse_chat_emits_error_and_done_when_engine_crashes(
    client: TestClient, db: Session, monkeypatch,
):
    """The SSE endpoint's last-resort except-net (streaming.py:event_generator)
    MUST emit BOTH an ``error`` and a ``done`` frame when
    ``engine.submit_message`` raises. Without the ``done`` terminator the
    frontend's reader loop never exits and the chat panel stays stuck on
    "AI 正在生成…" forever.

    Pre-fix the contract was only documented in code comments. This test
    pins both frames so a future refactor of the except-net can't
    silently drop the terminator.
    """
    db.add(ChatSession(id="s_boom", user_id="alice", title="t", session_type="general"))
    db.commit()

    async def boom(self):
        raise RuntimeError("simulated_engine_crash")
        # Yield ensures Python treats this as an async generator —
        # otherwise the function body would be a coroutine that
        # raises before returning the iterator, which is a different
        # error shape than the "iterate then raise" we want to test.
        yield  # noqa: F704

    from app.conversation.engine import ConversationEngine
    monkeypatch.setattr(ConversationEngine, "submit_message", boom)

    resp = client.post("/api/v1/chat/sse/s_boom", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.text

    # Both terminators must be present so the FE reader can exit cleanly.
    assert '"type": "error"' in body, (
        "missing error frame — FE would have no signal that the turn "
        "failed; body=%r" % body[:500]
    )
    assert '"type": "done"' in body, (
        "missing done terminator — FE reader loop hangs forever; "
        "body=%r" % body[:500]
    )
    # The raw exception message must propagate so debugging is possible.
    assert "simulated_engine_crash" in body


def test_sse_chat_mode_field_picks_strategy(client: TestClient, db: Session, monkeypatch):
    """``mode`` in the request body selects the strategy factory.

    Pre-fix, the SSE endpoint hardcoded ``make_chat_strategy()`` and the
    AGENT pill in the frontend was decorative — every request landed on
    the L1 chat path and the registered tool registry never reached
    the LLM. This test pins the dispatch contract:

      mode="chat"  (or omitted) → make_chat_strategy
      mode="agent"               → make_agent_strategy

    A wrong default ("agent") would unleash the full tool registry on
    every legacy client that doesn't send the field — exactly the
    regression we DO NOT want — so the back-compat default is
    asserted explicitly.
    """
    db.add(ChatSession(id="s_dispatch", user_id="alice", title="t", session_type="general"))
    db.commit()

    captured: dict[str, str] = {}

    class _StubStrategy:
        def __init__(self, label: str) -> None:
            captured["label"] = label

    # Patch at the source module — the endpoint lazy-imports both
    # factories from ``app.conversation`` inside its handler, so the
    # patch must hit the symbol there rather than on the endpoint
    # module (which never re-exports them as attributes).
    monkeypatch.setattr(
        "app.conversation.make_chat_strategy",
        lambda: _StubStrategy("chat"),
    )
    monkeypatch.setattr(
        "app.conversation.make_agent_strategy",
        lambda: _StubStrategy("agent"),
    )

    async def fake_submit(self):
        from app.conversation.events import HarnessEvent
        yield HarnessEvent.done(step=0, elapsed_ms=0)

    from app.conversation.engine import ConversationEngine
    monkeypatch.setattr(ConversationEngine, "submit_message", fake_submit)

    # Default (no mode) → chat.
    resp = client.post("/api/v1/chat/sse/s_dispatch", json={"message": "hi"})
    assert resp.status_code == 200
    assert captured["label"] == "chat", "default should be chat strategy"

    # Explicit chat → chat.
    resp = client.post(
        "/api/v1/chat/sse/s_dispatch", json={"message": "hi", "mode": "chat"},
    )
    assert resp.status_code == 200
    assert captured["label"] == "chat"

    # Explicit agent → agent.
    resp = client.post(
        "/api/v1/chat/sse/s_dispatch", json={"message": "hi", "mode": "agent"},
    )
    assert resp.status_code == 200
    assert captured["label"] == "agent", "mode='agent' must pick agent strategy"

    # Invalid mode → 422 (Pydantic Literal validation).
    resp = client.post(
        "/api/v1/chat/sse/s_dispatch", json={"message": "hi", "mode": "bogus"},
    )
    assert resp.status_code == 422
