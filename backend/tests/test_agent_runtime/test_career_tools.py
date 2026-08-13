from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.api import artifacts as artifacts_api
from app.api import career_process, career_profile
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.user import User

NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def career_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _NoCloseSession:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        self._inner.commit()


def _seed(db):
    owner = User(username=f"career-{uuid.uuid4().hex}", hashed_password="x")
    other = User(username=f"other-{uuid.uuid4().hex}", hashed_password="x")
    db.add_all([owner, other])
    db.flush()
    conversation = Conversation(user_id=owner.id, mode="agent")
    other_conversation = Conversation(user_id=other.id, mode="agent")
    db.add_all([conversation, other_conversation])
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=owner.id,
        mode="agent",
        message="manage career",
        status="running",
    )
    other_turn = ConversationTurn(
        conversation_id=other_conversation.id,
        user_id=other.id,
        mode="agent",
        message="other",
        status="running",
    )
    db.add_all([turn, other_turn])
    db.flush()
    confirmations = [
        ConversationMessage(
            conversation_id=conversation.id,
            seq=index,
            role="user",
            content=content,
        )
        for index, content in enumerate(
            ["请纳入跟踪", "我已约好面试"],
            start=1,
        )
    ]
    db.add_all(confirmations)
    db.flush()
    db.add(
        AgentToolCall(
            call_id="call-search-1",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=owner.id,
            tool_name="search_jobs",
            effect="read",
            arguments_json={"keywords": "backend"},
            timeout_seconds=20,
            status="completed",
            policy_decision="allow",
            policy_reason="read_allowed",
            result_json={
                "source": "lever",
                "jobs": [
                    {
                        "site": "example-co",
                        "job_id": "job-42",
                        "title": "Backend Engineer",
                        "location": "Shanghai",
                        "team": "Platform",
                        "hosted_url": "https://jobs.example.test/42",
                    }
                ],
            },
        )
    )
    db.commit()
    return (
        owner,
        other,
        conversation,
        other_conversation,
        turn,
        other_turn,
        confirmations,
    )


def _client(db, principal):
    async def current_user():
        return principal["user"]

    def current_db():
        yield db

    app = FastAPI()
    app.include_router(career_profile.router, prefix="/api/v1")
    app.include_router(career_process.router, prefix="/api/v1")
    app.include_router(artifacts_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    return TestClient(app)


def _call(name, payload, ctx):
    return asyncio.run(registry.dispatch(name, payload, ctx))


def test_career_tool_set_is_small_typed_and_policy_correct():
    expected = {
        "read_career_context": ToolEffect.READ,
        "track_search_job": ToolEffect.INTERNAL_WRITE,
        "record_career_event": ToolEffect.INTERNAL_WRITE,
        "read_artifacts": ToolEffect.READ,
        "save_artifact": ToolEffect.INTERNAL_WRITE,
    }
    for name, effect in expected.items():
        definition = registry.get(name)
        assert definition is not None
        assert definition.effect is effect
        assert definition.concurrency_safe is (effect is ToolEffect.READ)


@pytest.mark.parametrize(
    ("tool_name", "task_text", "authorized"),
    [
        ("track_search_job", "请跟踪这个岗位", True),
        ("track_search_job", "Track this job for me", True),
        ("track_search_job", "我想跟踪这个岗位", True),
        ("track_search_job", "不要跟踪这个岗位", False),
        ("track_search_job", "Do not save this job", False),
        ("track_search_job", "分析这个岗位是否合适", False),
        ("record_career_event", "请记录这次面试进展", True),
        ("record_career_event", "Record this interview status", True),
        ("record_career_event", "暂不记录这次面试进展", False),
        ("record_career_event", "Don't update the application status", False),
        ("record_career_event", "这次面试进展怎么样", False),
        ("record_career_event", "Save this interview recording as a file", False),
        ("save_artifact", "把这份材料保存为文档", True),
        ("save_artifact", "Save this report as an artifact", True),
        ("save_artifact", "先不保存这份材料", False),
        ("save_artifact", "Do not archive this document", False),
        ("save_artifact", "How do I save this document?", False),
        ("save_artifact", "帮我总结这份材料", False),
    ],
)
def test_career_internal_write_task_authorizers_are_explicit_and_fail_closed(
    tool_name,
    task_text,
    authorized,
):
    ctx = AgentToolContext(user_id="u", session_id="s", turn_id="t", user_pk=1)
    task_authorized, reversible = registry.policy_traits(
        tool_name,
        {},
        ctx,
        task_text,
    )

    assert task_authorized is authorized
    assert reversible is False


def test_ui_write_agent_read_and_agent_write_api_read(monkeypatch, career_db):
    from app.agent_runtime.tools import career as career_tools

    owner, _other, conversation, _, turn, _, confirmations = _seed(career_db)
    monkeypatch.setattr(
        career_tools,
        "SessionLocal",
        lambda: _NoCloseSession(career_db),
    )
    client = _client(career_db, {"user": owner})
    ctx = AgentToolContext(
        user_id=owner.username,
        user_pk=owner.id,
        session_id=conversation.id,
        turn_id=turn.id,
    )

    assert client.get("/api/v1/career-profile").status_code == 200
    profile = client.post(
        "/api/v1/career-profile/directions",
        json={
            "expected_profile_version": 1,
            "direction": {
                "label": "Backend",
                "lifecycle": "active",
                "priority": 1,
                "criteria": {"role_keywords": ["backend engineer"]},
            },
            "confirmation": {"kind": "user_edit"},
        },
    )
    assert profile.status_code == 200, profile.text
    context = _call("read_career_context", {}, ctx)
    assert context["career_profile"]["version"] == 2
    assert context["career_profile"]["directions"][0]["label"] == "Backend"

    tracked = _call(
        "track_search_job",
        {
            "search_call_id": "call-search-1",
            "job_id": "job-42",
            "confirmation_message_id": confirmations[0].id,
            "occurred_at": NOW.isoformat(),
            "idempotency_key": "track-job-42",
        },
        ctx,
    )
    opportunity_id = tracked["job_opportunity"]["id"]
    jobs = client.get("/api/v1/career-process/opportunities")
    assert jobs.status_code == 200
    assert jobs.json()[0]["external_job_id"] == "job-42"

    advanced = _call(
        "record_career_event",
        {
            "opportunity_id": opportunity_id,
            "kind": "interview_scheduled",
            "occurred_at": NOW.isoformat(),
            "confirmation_message_id": confirmations[1].id,
            "description": "用户确认一面已安排",
            "step_summary": "一面已安排",
            "idempotency_key": "event-interview-42",
            "next_action": {
                "content": "准备一面项目复盘",
                "time_kind": "flexible",
                "idempotency_key": "action-interview-42",
            },
        },
        ctx,
    )
    assert advanced["next_action"]["source_identity"] == advanced["process_event"]["id"]
    assert client.get("/api/v1/career-process/next-actions").json()[0]["content"] == (
        "准备一面项目复盘"
    )

    saved = _call(
        "save_artifact",
        {
            "operation_key": "save-plan-42",
            "artifact_kind": "interview_plan",
            "title": "一面准备计划",
            "content_text": "复盘项目架构与关键权衡。",
            "content_format": "markdown",
        },
        ctx,
    )
    artifact_id = saved["artifact"]["id"]
    artifact = client.get(f"/api/v1/artifacts/{artifact_id}")
    assert artifact.status_code == 200
    assert artifact.json()["current_version"]["source_turn_id"] == turn.id
    assert (
        _call("read_artifacts", {"artifact_id": artifact_id}, ctx)["artifacts"][0][
            "current_version"
        ]["content_text"]
        == "复盘项目架构与关键权衡。"
    )


def test_career_tools_reject_cross_tenant_sources_and_assets(monkeypatch, career_db):
    from app.agent_runtime.tools import career as career_tools

    owner, other, conversation, other_conversation, turn, other_turn, confirmations = (
        _seed(career_db)
    )
    monkeypatch.setattr(
        career_tools,
        "SessionLocal",
        lambda: _NoCloseSession(career_db),
    )
    owner_ctx = AgentToolContext(owner.username, conversation.id, turn.id, owner.id)
    other_ctx = AgentToolContext(
        other.username,
        other_conversation.id,
        other_turn.id,
        other.id,
    )
    saved = _call(
        "save_artifact",
        {
            "operation_key": "owner-only",
            "artifact_kind": "note",
            "title": "Owner only",
            "content_text": "private",
        },
        owner_ctx,
    )
    with pytest.raises(ValueError, match="not_found_or_not_owned"):
        _call(
            "track_search_job",
            {
                "search_call_id": "call-search-1",
                "job_id": "job-42",
                "confirmation_message_id": confirmations[0].id,
                "occurred_at": NOW.isoformat(),
                "idempotency_key": "cross-tenant",
            },
            other_ctx,
        )
    hidden = _call(
        "read_artifacts",
        {"artifact_id": saved["artifact"]["id"]},
        other_ctx,
    )
    assert hidden["error"] == "not_found_or_not_owned"
    assert _call("read_career_context", {}, other_ctx)["job_opportunities"] == []
