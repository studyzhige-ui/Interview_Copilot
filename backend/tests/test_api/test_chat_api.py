"""API tests for ``app.api.chat`` — session CRUD, transcript, history.

These exercise the router via FastAPI's TestClient with ``get_current_user``
and ``get_db`` overridden so we don't need a JWT or a real Postgres.

We construct a local in-memory SQLite engine inside the module because the
shared ``db_session`` fixture in ``tests/conftest.py`` references the missing
``app.models.interview`` module.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.api import memory as memory_api
from app.api.chat import sessions as conversations_mod
from app.core.security import get_current_user
from app.db.database import Base, get_db
import app.models  # noqa: F401  — ensure mappers registered
from app.models.chat import ConversationMessage, Conversation
from app.models.user import User


# ── Helpers ─────────────────────────────────────────────────────────────


def _uid(db: Session, username: str) -> int:
    """Seed a ``users`` row for ``username`` (idempotent) and return its
    integer ``users.id``.

    ``conversations.user_id`` is the integer ``users.id`` FK now (CLEANUP #2),
    and every chat ownership/scoping path resolves the request principal's
    username → ``users.id`` via ``resolve_user_pk`` before filtering. Seeded
    ``Conversation`` rows therefore must carry the integer pk of a real
    ``users`` row, not the username string.
    """
    row = db.query(User).filter(User.username == username).first()
    if row is None:
        row = User(username=username, hashed_password="x")
        db.add(row)
        db.commit()
    return row.id


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

    # The v3 memory services (memory_document_service /
    # memory_ability_state_service / _memory_audit) bypass FastAPI's
    # ``get_db`` and open their own session via ``SessionLocal()`` imported
    # at module-load time. To keep memory-endpoint tests honest we must
    # rebind every such reference to a sessionmaker that points at THIS
    # in-memory engine — otherwise those endpoints would talk to the real
    # configured database (or fail with "no such table: memory_documents").
    import app.services.memory._db_helpers as _helpers_mod
    import app.services.memory._memory_audit as _audit_mod
    import app.services.memory.memory_ability_state_service as _ability_mod
    import app.services.memory.memory_document_service as _doc_mod
    # Includes ``_db_helpers`` because the services route their
    # ``SessionLocal()`` opens through ``_db_helpers.session_scope`` —
    # rebinding only the service modules' own ``SessionLocal`` leaves the
    # helper's binding pointed at the real configured DB.
    for _mod in (_helpers_mod, _audit_mod, _ability_mod, _doc_mod):
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
    alice_pk = _uid(db, "alice")  # endpoint resolves "alice" → this pk on insert
    resp = client.post("/api/v1/chat/sessions", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "general"
    assert body["title"] == "通用对话"
    # DB-side effect: row exists, owned by alice's integer pk (not the username).
    row = db.query(Conversation).filter(Conversation.id == body["session_id"]).first()
    assert row is not None
    assert row.user_id == alice_pk


def test_create_debrief_session_requires_existing_interview(client: TestClient):
    resp = client.post(
        "/api/v1/chat/sessions",
        json={"type": "debrief", "subject_id": "ir_missing"},
    )
    assert resp.status_code == 404


def test_list_conversations_is_user_scoped(client: TestClient, db: Session):
    # Seed BOTH users as real rows so isolation is exercised via DISTINCT
    # integer pks (not a string-vs-int type accident): the list endpoint
    # filters Conversation.user_id == resolve_user_pk(db, "alice").
    db.add_all([
        Conversation(id="s_a", user_id=_uid(db, "alice"), title="A", type="general"),
        Conversation(id="s_b", user_id=_uid(db, "bob"),   title="B", type="general"),
    ])
    db.commit()
    resp = client.get("/api/v1/chat/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert ids == ["s_a"]


def test_rename_session_validates_non_empty(client: TestClient, db: Session):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="old", type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "   "})
    assert resp.status_code == 400


def test_rename_session_updates_title(client: TestClient, db: Session):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="old", type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "new"})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Conversation,"s1").title == "new"


def test_rename_session_rejects_other_user(client: TestClient, db: Session):
    # alice (authed principal) and bob are distinct real users → the 404 is a
    # genuine pk mismatch (alice_pk != bob_pk), not an unseeded user → None.
    _uid(db, "alice")
    db.add(Conversation(id="s_bob", user_id=_uid(db, "bob"), title="old", type="general"))
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s_bob/title", json={"title": "new"})
    assert resp.status_code == 404


def test_delete_session_removes_row_and_messages(client: TestClient, db: Session):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="general"))
    # conversation_messages has NO user_id (keyed via session_id FK) — leave it as-is.
    db.add(ConversationMessage(conversation_id="s1", seq=1, role="User", content="hi"))
    db.commit()
    resp = client.delete("/api/v1/chat/sessions/s1")
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Conversation,"s1") is None
    assert db.query(ConversationMessage).filter(ConversationMessage.conversation_id == "s1").count() == 0


# ── /chat/history ─────────────────────────────────────────────────────────


def test_history_returns_in_seq_order(client: TestClient, db: Session):
    # 0018 reverted the conversation_id split — messages are scoped only
    # by session_id again.
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="general"))
    db.add(ConversationMessage(conversation_id="s1", seq=1, role="User", content="hi"))
    db.add(ConversationMessage(conversation_id="s1", seq=2, role="AI", content="hello"))
    db.commit()
    resp = client.get("/api/v1/chat/history", params={"session_id": "s1"})
    assert resp.status_code == 200
    seqs = [m["seq"] for m in resp.json()]
    assert seqs == [1, 2]


def test_history_404_for_other_user(client: TestClient, db: Session):
    _uid(db, "alice")  # authed principal — a distinct real user
    db.add(Conversation(id="s_bob", user_id=_uid(db, "bob"), title="t", type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/history", params={"session_id": "s_bob"})
    assert resp.status_code == 404


# ── /chat/transcript ──────────────────────────────────────────────────────


def test_transcript_returns_structured_state(client: TestClient, db: Session, monkeypatch):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="debrief"))
    db.commit()

    class FakeTranscriptSvc:
        @staticmethod
        def get_session_meta(session_id):
            return {
                "turn_count": 2,
                "compaction_cursor": 4,
                "type": "debrief",
                "current_conversation_id": "s1",
            }

        @staticmethod
        def get_full_transcript(session_id, conversation_id=None):
            # The real signature picked up a ``conversation_id`` kwarg in
            # migration 0015; the handler always passes it through (even
            # when None) so the fake must accept it.
            return [{"seq": 1, "role": "User", "content": "hi", "created_at": "t"}]

    monkeypatch.setattr(conversations_mod, "transcript_service", FakeTranscriptSvc)
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "debrief"
    assert body["compaction_cursor"] == 4
    assert body["total_messages"] == 1


def test_transcript_404_for_other_user(client: TestClient, db: Session):
    _uid(db, "alice")  # authed principal — a distinct real user
    db.add(Conversation(id="s_bob", user_id=_uid(db, "bob"), title="t", type="general"))
    db.commit()
    resp = client.get("/api/v1/chat/transcript", params={"session_id": "s_bob"})
    assert resp.status_code == 404


# ── /memory/* (v3) ────────────────────────────────────────────────────────


def test_memory_overview_returns_v3_bundle(client: TestClient):
    """Smoke: /memory/overview returns the v3 bundle (user_profile +
    learning_strategy bodies + active ability states), empty for a user
    with no memory yet."""
    resp = client.get("/api/v1/memory/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "user_profile_body" in body
    assert "learning_strategy_body" in body
    assert "ability_states" in body
    # Fresh user → empty bodies + empty ability list (not None / missing).
    assert body["user_profile_body"] == ""
    assert body["learning_strategy_body"] == ""
    assert isinstance(body["ability_states"], list)
    assert body["ability_states"] == []
    # The retired knowledge/strategy/habit doc fields are gone.
    assert "knowledge_topics" not in body
    assert "strategy_body" not in body
    assert "habit_body" not in body


def test_memory_ability_state_delete_404_when_missing(client: TestClient):
    """Archiving a non-existent ability state returns 404 (replaces the
    retired ``/memory/knowledge/topics/{id}`` route)."""
    resp = client.delete("/api/v1/memory/ability-states/does_not_exist")
    assert resp.status_code == 404


# ── /chat/sse — streaming (smoke test) ────────────────────────────────────


def test_sse_chat_endpoint_streams_chunks(client: TestClient, db: Session, monkeypatch):
    """Smoke test for the SSE pipeline: dependency-overridden user owns the
    session, the engine yields HarnessEvent text_delta + done, and the
    response is an SSE stream terminated with ``"type": "done"``."""
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="general"))
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


def _seed_started_mock(db: Session, *, username="alice", record_id="ir_m", conv_id="c_m"):
    """Seed a started mock: record(mock_in_progress) + conversation + opening
    message + runtime(in_progress), as the start endpoint would have."""
    import json as _json

    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime

    pk = _uid(db, username)
    db.add(InterviewRecord(
        id=record_id, user_id=pk, source="mock", title="模拟面试",
        status="mock_in_progress",
        resume_text_snapshot="三年后端经验", jd_text_snapshot="JD",
    ))
    db.add(Conversation(
        id=conv_id, user_id=pk, title="模拟面试", type="mock_interview",
        subject_type="interview_record", subject_id=record_id,
    ))
    db.add(ConversationMessage(
        conversation_id=conv_id, seq=1, role="assistant", content="请做个自我介绍",
    ))
    db.add(MockInterviewRuntime(
        id="mir_m", user_id=pk, interview_record_id=record_id, conversation_id=conv_id,
        status="in_progress", current_stage_key="self_intro",
        plan_json=_json.dumps({"stages": [
            {"key": "self_intro", "title": "自我介绍"},
            {"key": "candidate_questions", "title": "反问"},
        ]}),
    ))
    db.commit()
    return record_id, conv_id


def test_mock_start_creates_record_conversation_runtime(
    client: TestClient, db: Session, monkeypatch,
):
    """``POST /mock-interviews/start`` atomically creates the record
    (mock_in_progress), the bound conversation, the runtime (in_progress) and
    the opening interviewer message — resolving resume context from the
    personal ``resumes`` entity. No pre-created chat session is required."""
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.models.resume import Resume

    pk = _uid(db, "alice")
    db.add(Resume(
        id="rsm_1", user_id=pk, title="我的简历", is_default=True,
        raw_text_snapshot="三年后端开发经验，主导过推荐系统项目", parse_status="ready",
    ))
    db.commit()
    # No parsed sections → falls back to the entity's raw_text_snapshot.
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_resume",
        lambda resume_id, user_id=None: [],
    )

    resp = client.post(
        "/api/v1/mock-interviews/start",
        json={"resume_id": "rsm_1", "jd_text": "JD content", "interviewer_style": "professional"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["interview_record_id"] and body["conversation_id"] and body["runtime_id"]
    assert body["current_stage_key"] == "self_intro"
    assert "自我介绍" in body["current_question"]
    assert [p["key"] for p in body["plan_phases"]][0] == "self_intro"

    # The resume entity's raw_text_snapshot was frozen onto the record.
    record = db.query(InterviewRecord).filter(
        InterviewRecord.id == body["interview_record_id"]
    ).first()
    assert record is not None and record.status == "mock_in_progress"
    assert "推荐系统" in (record.resume_text_snapshot or "")
    # Runtime exists and is in_progress, pointed at the opening message.
    rt = db.query(MockInterviewRuntime).filter(
        MockInterviewRuntime.id == body["runtime_id"]
    ).first()
    assert rt is not None and rt.status == "in_progress"
    assert rt.current_question_message_id is not None


def test_mock_answer_appends_messages_and_advances(
    client: TestClient, db: Session, monkeypatch,
):
    """``POST /mock-interviews/{id}/answer`` persists the candidate's answer,
    generates the next interviewer line, persists it, and advances the runtime
    stage — without any Director/retry machinery."""
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.services.interview.mock_interview_service import NextTurn

    record_id, conv_id = _seed_started_mock(db)

    async def fake_next_turn(**kwargs):
        return NextTurn(
            interviewer_message="好的。讲讲你最近的项目？",
            next_stage_key="candidate_questions",
            is_ready_to_finish=False,
        )

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_next_turn",
        fake_next_turn,
    )

    resp = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer",
        json={"answer_text": "我叫小王，三年后端。"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["interviewer_message"].startswith("好的")
    assert body["current_stage_key"] == "candidate_questions"
    assert body["is_ready_to_finish"] is False

    # The user answer + the new assistant line are both persisted (opening + 2).
    msgs = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .order_by(ConversationMessage.seq)
        .all()
    )
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]
    rt = db.query(MockInterviewRuntime).filter(
        MockInterviewRuntime.interview_record_id == record_id
    ).first()
    assert rt.current_stage_key == "candidate_questions"


def test_mock_finish_transitions_to_processing_review_and_dispatches(
    client: TestClient, db: Session, monkeypatch,
):
    """``finish`` flips the record to processing_review and dispatches the
    review task; the record drops out of the review list until review_ready."""
    from app.models.interview_record import InterviewRecord

    record_id, conv_id = _seed_started_mock(db)
    # Finish requires at least one answered turn.
    db.add(ConversationMessage(conversation_id=conv_id, seq=2, role="user", content="我的回答"))
    db.commit()

    dispatched: dict = {}

    class _FakeAsyncResult:
        id = "task_123"

    def fake_delay(rid):
        dispatched["record_id"] = rid
        return _FakeAsyncResult()

    monkeypatch.setattr("app.worker.tasks.process_interview_analysis.delay", fake_delay)

    resp = client.post(f"/api/v1/mock-interviews/{record_id}/finish")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "processing_review", "record_id": record_id}
    assert dispatched["record_id"] == record_id

    db.expire_all()
    assert db.get(InterviewRecord, record_id).status == "processing_review"


def test_mock_abandon_deletes_everything(client: TestClient, db: Session):
    """``DELETE /mock-interviews/{id}`` removes the conversation + messages +
    runtime + draft record for an unfinished mock."""
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime

    record_id, conv_id = _seed_started_mock(db)

    resp = client.delete(f"/api/v1/mock-interviews/{record_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "deleted", "record_id": record_id}

    db.expire_all()
    assert db.get(InterviewRecord, record_id) is None
    assert db.get(Conversation, conv_id) is None
    assert db.query(MockInterviewRuntime).filter(
        MockInterviewRuntime.interview_record_id == record_id
    ).first() is None
    assert db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == conv_id
    ).count() == 0


def test_in_progress_returns_active_runtime(client: TestClient, db: Session):
    """``GET /mock-interviews/in-progress`` surfaces the user's active runtime
    for the resume banner."""
    record_id, conv_id = _seed_started_mock(db)
    resp = client.get("/api/v1/mock-interviews/in-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_in_progress"] is True
    assert body["record_id"] == record_id
    assert body["conversation_id"] == conv_id
    assert body["current_stage_key"] == "self_intro"


def test_in_progress_false_when_no_active_runtime(client: TestClient, db: Session):
    _uid(db, "alice")
    resp = client.get("/api/v1/mock-interviews/in-progress")
    assert resp.status_code == 200
    assert resp.json()["has_in_progress"] is False


def test_sse_chat_404_for_other_user(client: TestClient, db: Session):
    _uid(db, "alice")  # authed principal — a distinct real user
    db.add(Conversation(id="s_bob", user_id=_uid(db, "bob"), title="t", type="general"))
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
    db.add(Conversation(id="s_boom", user_id=_uid(db, "alice"), title="t", type="general"))
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
    # The user-facing error frame is HUMANIZED: the raw exception text
    # (``simulated_engine_crash``) must NOT leak to the client — it goes to
    # the server log instead. This is the point of routing the last-resort
    # net through ``humanize_error`` (no raw ``Error code: 402 - {...}``
    # dumps reaching the chat panel).
    assert "simulated_engine_crash" not in body


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
    db.add(Conversation(id="s_dispatch", user_id=_uid(db, "alice"), title="t", type="general"))
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
