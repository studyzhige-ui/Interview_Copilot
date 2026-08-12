"""API tests for ``app.api.chat`` — session CRUD, transcript, history.

These exercise the router via FastAPI's TestClient with ``get_current_user``
and ``get_db`` overridden so we don't need a JWT or a real Postgres.

We construct a local in-memory SQLite engine inside the module because the
shared ``db_session`` fixture in ``tests/conftest.py`` references the missing
``app.models.interview`` module.
"""

from __future__ import annotations

import json
from typing import Iterator

import app.models  # noqa: F401  — ensure mappers registered
import pytest
from app.api import chat as chat_api
from app.api import memory as memory_api
from app.api.chat import sessions as conversations_mod
from app.api.interviews import mock as mock_api
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def test_terminal_sse_recovery_preserves_failure_and_cancellation():
    from app.api.chat.streaming import _recovery_events

    failed = [json.loads(event) for event in _recovery_events("failed", "worker died")]
    cancelled = [json.loads(event) for event in _recovery_events("cancelled", None)]
    completed = [json.loads(event) for event in _recovery_events("completed", None)]

    assert [event["type"] for event in failed] == ["error", "done"]
    assert failed[0]["data"]["error"] == "worker died"
    assert [event["type"] for event in cancelled] == ["error", "done"]
    assert cancelled[0]["data"]["error"] == "本轮已取消"
    assert [event["type"] for event in completed] == ["done"]


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
    app.include_router(mock_api.router, prefix="/api/v1")
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
    assert row.mode == "agent"


def test_general_turn_cannot_downgrade_career_runtime_to_chat(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(
        Conversation(
            id="career_mode",
            user_id=user_id,
            title="Career",
            type="general",
            mode="chat",
        )
    )
    db.commit()

    async def ping():
        return None

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", lambda _turn_id: None)

    response = client.post(
        "/api/v1/chat/career_mode/turns",
        json={"message": "直接回答也由 Agent 决策", "mode": "chat"},
    )

    assert response.status_code == 202
    turn = db.get(ConversationTurn, response.json()["turn_id"])
    assert turn is not None and turn.mode == "agent"
    db.expire_all()
    assert db.get(Conversation, "career_mode").mode == "agent"


def test_create_turn_is_backgrounded(client: TestClient, db: Session, monkeypatch):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(Conversation(id="s_turn", user_id=user_id, title="T", type="general"))
    db.commit()

    async def ping():
        return None

    scheduled: list[str] = []
    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", scheduled.append)
    response = client.post(
        "/api/v1/chat/s_turn/turns",
        json={
            "message": "继续完成任务",
            "mode": "agent",
            "question_indexes": [5, 2, 5],
        },
    )

    assert response.status_code == 202
    turn = db.get(ConversationTurn, response.json()["turn_id"])
    assert turn and turn.status == "pending" and turn.mode == "agent"
    assert turn.question_indexes_json == [5, 2]
    assert db.get(Conversation, "s_turn").active_turn_id == turn.id
    user_message = (
        db.query(ConversationMessage)
        .filter_by(
            conversation_id="s_turn",
            seq=turn.user_message_seq,
        )
        .one()
    )
    assert user_message.role == "User" and user_message.content == "继续完成任务"
    assert scheduled == [turn.id]


def test_create_turn_dispatch_failure_is_terminal(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.services.chat import turn_executor
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    db.add(Conversation(id="s_dispatch", user_id=user_id, title="T", type="general"))
    db.commit()

    async def ping():
        return None

    def fail_dispatch(_turn_id: str):
        raise ConnectionError("broker offline")

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    monkeypatch.setattr(turn_executor, "schedule_turn", fail_dispatch)
    response = client.post(
        "/api/v1/chat/s_dispatch/turns",
        json={"message": "继续完成任务", "mode": "agent"},
    )

    assert response.status_code == 503
    turn = db.query(ConversationTurn).filter_by(conversation_id="s_dispatch").one()
    db.refresh(turn)
    assert turn.status == "failed"
    assert db.get(Conversation, "s_dispatch").active_turn_id is None


def test_create_turn_rejects_parallel_turn(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    conversation = Conversation(id="s_busy", user_id=user_id, title="T", type="general")
    turn = ConversationTurn(
        id="turn_busy",
        conversation_id="s_busy",
        user_id=user_id,
        mode="agent",
        message="work",
        status="running",
    )
    conversation.active_turn_id = turn.id
    db.add_all([conversation, turn])
    db.commit()

    async def ping():
        return None

    monkeypatch.setattr(turn_event_buffer, "ping", ping)
    response = client.post(
        "/api/v1/chat/s_busy/turns",
        json={"message": "duplicate", "mode": "agent"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["turn_id"] == "turn_busy"


def test_cancel_pending_turn_releases_session(
    client: TestClient, db: Session, monkeypatch
):
    from app.services.chat.turn_event_buffer import turn_event_buffer

    user_id = _uid(db, "alice")
    conversation = Conversation(
        id="cancel-session",
        user_id=user_id,
        title="T",
        type="general",
        active_turn_id="cancel-turn",
    )
    turn = ConversationTurn(
        id="cancel-turn",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        message="work",
        status="pending",
    )
    db.add_all([conversation, turn])
    db.commit()

    async def request_cancel(_turn_id: str):
        return None

    monkeypatch.setattr(turn_event_buffer, "request_cancel", request_cancel)
    response = client.post("/api/v1/chat/cancel-session/turns/cancel-turn/cancel")

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    db.expire_all()
    assert db.get(ConversationTurn, turn.id).status == "cancelled"
    assert db.get(Conversation, conversation.id).active_turn_id is None


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
    db.add_all(
        [
            Conversation(
                id="s_a", user_id=_uid(db, "alice"), title="A", type="general"
            ),
            Conversation(id="s_b", user_id=_uid(db, "bob"), title="B", type="general"),
        ]
    )
    db.commit()
    resp = client.get("/api/v1/chat/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert ids == ["s_a"]


def test_rename_session_validates_non_empty(client: TestClient, db: Session):
    db.add(
        Conversation(id="s1", user_id=_uid(db, "alice"), title="old", type="general")
    )
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "   "})
    assert resp.status_code == 400


def test_rename_session_updates_title(client: TestClient, db: Session):
    db.add(
        Conversation(id="s1", user_id=_uid(db, "alice"), title="old", type="general")
    )
    db.commit()
    resp = client.patch("/api/v1/chat/sessions/s1/title", json={"title": "new"})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(Conversation, "s1").title == "new"


def test_rename_session_rejects_other_user(client: TestClient, db: Session):
    # alice (authed principal) and bob are distinct real users → the 404 is a
    # genuine pk mismatch (alice_pk != bob_pk), not an unseeded user → None.
    _uid(db, "alice")
    db.add(
        Conversation(id="s_bob", user_id=_uid(db, "bob"), title="old", type="general")
    )
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
    assert db.get(Conversation, "s1") is None
    assert (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == "s1")
        .count()
        == 0
    )


def test_delete_session_rejects_active_turn(client: TestClient, db: Session):
    user_id = _uid(db, "alice")
    conversation = Conversation(
        id="active-session",
        user_id=user_id,
        title="t",
        type="general",
        active_turn_id="active-turn",
    )
    turn = ConversationTurn(
        id="active-turn",
        conversation_id=conversation.id,
        user_id=user_id,
        mode="agent",
        message="work",
        status="running",
    )
    db.add_all([conversation, turn])
    db.commit()

    response = client.delete("/api/v1/chat/sessions/active-session")
    assert response.status_code == 409


# ── /chat/transcript ──────────────────────────────────────────────────────


def test_transcript_returns_structured_state(
    client: TestClient, db: Session, monkeypatch
):
    db.add(Conversation(id="s1", user_id=_uid(db, "alice"), title="t", type="debrief"))
    db.commit()

    class FakeTranscriptSvc:
        @staticmethod
        def get_session_meta(session_id, *, db=None):
            return {
                "turn_count": 2,
                "compaction_cursor": 4,
                "type": "debrief",
                "current_conversation_id": "s1",
            }

        @staticmethod
        def get_full_transcript(session_id, *, db=None):
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


def _seed_started_mock(
    db: Session, *, username="alice", record_id="ir_m", conv_id="c_m"
):
    """Seed a started mock: record(mock_in_progress) + conversation + opening
    message + runtime(in_progress), as the start endpoint would have."""
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime

    pk = _uid(db, username)
    db.add(
        InterviewRecord(
            id=record_id,
            user_id=pk,
            source="mock",
            title="模拟面试",
            status="mock_in_progress",
            resume_text_snapshot="三年后端经验",
            jd_text_snapshot="JD",
        )
    )
    db.add(
        Conversation(
            id=conv_id,
            user_id=pk,
            title="模拟面试",
            type="mock_interview",
            subject_type="interview_record",
            subject_id=record_id,
        )
    )
    db.flush()
    opening = ConversationMessage(
        conversation_id=conv_id,
        seq=1,
        role="assistant",
        content="请做个自我介绍",
    )
    db.add(opening)
    db.flush()
    db.add(
        MockInterviewRuntime(
            user_id=pk,
            interview_record_id=record_id,
            conversation_id=conv_id,
            current_stage_key="self_intro",
            current_question_message_id=opening.id,
            plan_json=[
                {"key": "self_intro", "title": "自我介绍"},
                {"key": "candidate_questions", "title": "反问"},
            ],
            interviewer_style="professional",
            target_question_count=20,
        )
    )
    db.commit()
    return record_id, conv_id


def test_mock_start_creates_record_conversation_runtime(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    """``POST /mock-interviews/start`` atomically creates the record
    (mock_in_progress), the bound conversation, the runtime (in_progress) and
    the opening interviewer message — resolving resume context from the
    personal ``resumes`` entity. No pre-created chat session is required."""
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.models.resume import Resume

    pk = _uid(db, "alice")
    db.add(
        Resume(
            id="rsm_1",
            user_id=pk,
            title="我的简历",
            is_default=True,
            raw_text_snapshot="三年后端开发经验，主导过推荐系统项目",
            parse_status="ready",
        )
    )
    db.commit()
    # No parsed sections → falls back to the entity's raw_text_snapshot.
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_resume",
        lambda resume_id, user_id=None: [],
    )
    plan_payload = {
        "guidance": {
            "self_intro": "判断与后端岗位的整体匹配。",
            "resume_project_deep_dive": "围绕推荐系统验证个人贡献。",
            "role_technical_assessment": "抽样考察岗位相关技术能力。",
            "candidate_questions": "只根据 JD 回答候选人反问。",
        }
    }

    class _PlanningLLM:
        def complete(self, *args, **kwargs):
            return type(
                "PlanningResponse",
                (),
                {"text": json.dumps(plan_payload, ensure_ascii=False)},
            )()

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.get_llm_for_role",
        lambda *args, **kwargs: _PlanningLLM(),
    )

    resp = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": "rsm_1",
            "jd_text": "高级后端工程师岗位，要求系统设计、数据库和稳定性经验。",
            "interviewer_style": "professional",
            "target_question_count": 30,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"record_id", "message"}
    assert body["record_id"]
    assert body["message"]["speaker"] == "interviewer"
    assert "自我介绍" in body["message"]["text"]

    # The resume entity's raw_text_snapshot was frozen onto the record.
    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == body["record_id"])
        .first()
    )
    assert record is not None and record.status == "mock_in_progress"
    assert "推荐系统" in (record.resume_text_snapshot or "")
    # Runtime exists and points at the opening message.
    rt = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == body["record_id"])
        .first()
    )
    assert rt is not None
    assert rt.current_question_message_id is not None
    assert rt.target_question_count == 30


def test_mock_start_rejects_resume_that_has_not_been_parsed(
    client: TestClient,
    db: Session,
):
    from app.models.resume import Resume

    pk = _uid(db, "alice")
    db.add(
        Resume(
            id="rsm_pending",
            user_id=pk,
            title="仍在解析的简历",
            is_default=True,
            parse_status="pending",
        )
    )
    db.commit()

    response = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": "rsm_pending",
            "jd_text": "这是满足长度要求的后端工程师岗位说明文本。",
        },
    )

    assert response.status_code == 409
    assert "解析" in response.json()["detail"]


def test_mock_answer_audio_transcribes_and_stores_one_asset(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_draft",
        conv_id="c_audio_draft",
    )

    async def fake_transcribe(_path: str, *, language: str = "zh") -> str:
        assert language == "zh"
        return "我负责了核心接口的性能优化"

    stored: dict[str, bytes] = {}

    def fake_store(file_obj, object_key: str, content_type: str | None = None) -> str:
        stored["body"] = file_obj.read()
        stored["content_type"] = (content_type or "").encode()
        return f"s3://test/{object_key}"

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.uploads.file_asset_service.upload_file_to_owned_key",
        fake_store,
    )

    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3
    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"text", "audio_file_asset_id"}
    assert body["text"] == "我负责了核心接口的性能优化"
    assert stored["body"] == audio

    asset = db.get(FileAsset, body["audio_file_asset_id"])
    assert asset is not None
    assert asset.purpose == "mock_audio_clip"
    assert asset.upload_status == "uploaded"
    assert asset.validation_status == "passed"
    assert asset.size_bytes == len(audio)


def test_mock_answer_audio_does_not_store_empty_transcript(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_empty",
        conv_id="c_audio_empty",
    )

    async def fake_transcribe(_path: str, *, language: str = "zh") -> str:
        return "  "

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fake_transcribe,
    )
    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3

    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 422
    assert "重新录制" in response.json()["detail"]
    assert db.query(FileAsset).count() == 0


def test_mock_answer_audio_reports_storage_failure_and_marks_asset_failed(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_storage_failure",
        conv_id="c_audio_storage_failure",
    )

    async def fake_transcribe(_path: str, *, language: str = "zh") -> str:
        return "已经成功转写"

    def fail_store(*_args, **_kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fake_transcribe,
    )
    monkeypatch.setattr(
        "app.services.uploads.file_asset_service.upload_file_to_owned_key",
        fail_store,
    )
    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3

    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 503
    assert "录音仍保留" in response.json()["detail"]
    asset = db.query(FileAsset).one()
    assert asset.upload_status == "failed"
    assert asset.validation_status == "failed"


def test_mock_answer_audio_reports_unavailable_transcription_without_storing(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.file_asset import FileAsset
    from app.services.voice.short_clip_transcription import TranscriptionUnavailable

    record_id, _ = _seed_started_mock(
        db,
        record_id="ir_audio_asr_unavailable",
        conv_id="c_audio_asr_unavailable",
    )

    async def fail_transcribe(_path: str, *, language: str = "zh") -> str:
        raise TranscriptionUnavailable("model unavailable")

    monkeypatch.setattr(
        "app.services.voice.short_clip_transcription.transcribe_short_clip",
        fail_transcribe,
    )
    audio = b"\x1a\x45\xdf\xa3" + b"mock-webm-audio" * 3

    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer-audio",
        files={"file": ("answer.webm", audio, "audio/webm")},
    )

    assert response.status_code == 503
    assert "录音仍保留" in response.json()["detail"]
    assert db.query(FileAsset).count() == 0


def test_mock_answer_appends_messages_and_advances(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    """``POST /mock-interviews/{id}/answer`` persists the candidate's answer,
    generates the next interviewer line, persists it, and advances the runtime
    stage — without any Director/retry machinery."""
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.services.interview.mock_interview_service import NextTurn

    record_id, conv_id = _seed_started_mock(db)
    runtime = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .one()
    )

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
        json={
            "answer_text": "我叫小王，三年后端。",
            "question_message_id": runtime.current_question_message_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"message", "end_suggested"}
    assert body["message"]["speaker"] == "interviewer"
    assert body["message"]["text"].startswith("好的")
    assert body["end_suggested"] is False

    # The user answer + the new assistant line are both persisted (opening + 2).
    msgs = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .order_by(ConversationMessage.seq)
        .all()
    )
    assert [m.role for m in msgs] == ["assistant", "user", "assistant"]
    rt = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .first()
    )
    assert rt.current_stage_key == "candidate_questions"


def test_mock_answer_failure_preserves_candidate_answer_for_recovery(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.services.interview.mock_interview_service import (
        NextTurnGenerationError,
    )

    record_id, conv_id = _seed_started_mock(
        db,
        record_id="ir_answer_recovery",
        conv_id="c_answer_recovery",
    )
    runtime = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .one()
    )

    async def fail_next_turn(**kwargs):
        raise NextTurnGenerationError("LLM unavailable")

    monkeypatch.setattr(
        "app.services.interview.mock_interview_service.generate_next_turn",
        fail_next_turn,
    )
    response = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer",
        json={
            "answer_text": "这段回答必须被保留",
            "question_message_id": runtime.current_question_message_id,
        },
    )

    assert response.status_code == 503
    assert "回答已保存" in response.json()["detail"]
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .order_by(ConversationMessage.seq)
        .all()
    )
    assert [(message.role, message.content) for message in messages] == [
        ("assistant", "请做个自我介绍"),
        ("user", "这段回答必须被保留"),
    ]
    db.refresh(runtime)
    assert runtime.answer_claimed_at is None


def test_mock_finish_transitions_to_processing_review_and_dispatches(
    client: TestClient,
    db: Session,
    monkeypatch,
):
    """``finish`` flips the record to processing_review and dispatches the
    review task; the record drops out of the review list until review_ready."""
    from app.models.interview_record import InterviewRecord

    record_id, conv_id = _seed_started_mock(db)
    # Finish requires at least one answered turn.
    db.add(
        ConversationMessage(
            conversation_id=conv_id, seq=2, role="user", content="我的回答"
        )
    )
    db.commit()

    dispatched: dict = {}

    class _FakeAsyncResult:
        id = "task_123"

    def fake_delay(rid):
        dispatched["record_id"] = rid
        return _FakeAsyncResult()

    monkeypatch.setattr(
        "app.services.interview.mock_flow.dispatch_mock_interview_review", fake_delay
    )

    resp = client.post(f"/api/v1/mock-interviews/{record_id}/finish")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "processing_review", "record_id": record_id}
    assert dispatched["record_id"] == record_id

    db.expire_all()
    assert db.get(InterviewRecord, record_id).status == "processing_review"
    from app.models.mock_interview_runtime import MockInterviewRuntime

    assert db.get(MockInterviewRuntime, record_id) is None


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
    assert (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .first()
        is None
    )
    assert (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conv_id)
        .count()
        == 0
    )


def test_in_progress_returns_active_runtime(client: TestClient, db: Session):
    """``GET /mock-interviews/in-progress`` surfaces the user's active runtime
    for the resume banner."""
    record_id, conv_id = _seed_started_mock(db)
    resp = client.get("/api/v1/mock-interviews/in-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_in_progress"] is True
    assert body["record_id"] == record_id
    assert set(body) == {
        "has_in_progress",
        "record_id",
        "title",
        "last_activity_at",
    }


def test_live_state_returns_complete_user_facing_conversation(
    client: TestClient,
    db: Session,
):
    record_id, conv_id = _seed_started_mock(db)
    db.add_all(
        [
            ConversationMessage(
                conversation_id=conv_id,
                seq=2,
                role="user",
                content="我的第一段回答",
            ),
            ConversationMessage(
                conversation_id=conv_id,
                seq=3,
                role="assistant",
                content="请继续讲讲项目难点",
            ),
        ]
    )
    db.commit()

    response = client.get(f"/api/v1/mock-interviews/{record_id}/live-state")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["speaker"] for message in messages] == [
        "interviewer",
        "candidate",
        "interviewer",
    ]
    assert [message["text"] for message in messages] == [
        "请做个自我介绍",
        "我的第一段回答",
        "请继续讲讲项目难点",
    ]


def test_in_progress_false_when_no_active_runtime(client: TestClient, db: Session):
    _uid(db, "alice")
    resp = client.get("/api/v1/mock-interviews/in-progress")
    assert resp.status_code == 200
    assert resp.json()["has_in_progress"] is False


# ── Phase 5 (MOCK-3): endpoint-level guard mappings ──────────────────────


def test_answer_with_stale_token_maps_to_409(client: TestClient, db: Session):
    from app.models.mock_interview_runtime import MockInterviewRuntime

    record_id, conv_id = _seed_started_mock(db, record_id="ir_tok", conv_id="c_tok")
    rt = (
        db.query(MockInterviewRuntime)
        .filter(MockInterviewRuntime.interview_record_id == record_id)
        .first()
    )
    rt.current_question_message_id = 42
    db.commit()

    resp = client.post(
        f"/api/v1/mock-interviews/{record_id}/answer",
        json={"answer_text": "回答", "question_message_id": 41},
    )
    assert resp.status_code == 409
    assert "已推进" in resp.json()["detail"]


def test_finish_on_non_in_progress_record_maps_to_409(client: TestClient, db: Session):
    from app.models.interview_record import InterviewRecord

    record_id, _ = _seed_started_mock(db, record_id="ir_fin409", conv_id="c_fin409")
    rec = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
    rec.status = "processing_review"  # a double-click already dispatched
    db.commit()

    resp = client.post(f"/api/v1/mock-interviews/{record_id}/finish")
    assert resp.status_code == 409


def test_start_with_active_run_maps_to_409(client: TestClient, db: Session):
    _seed_started_mock(db, record_id="ir_dup", conv_id="c_dup")
    resp = client.post(
        "/api/v1/mock-interviews/start",
        json={
            "resume_id": "any",
            "jd_text": "这是满足接口校验长度要求的岗位说明文本内容。",
        },
    )
    assert resp.status_code == 409
    assert "进行中" in resp.json()["detail"]
