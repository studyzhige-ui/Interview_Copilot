from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

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
from app.models.artifact import ArtifactVersion
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
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
        message="请纳入跟踪，并记录我已约好面试",
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
            ["请纳入跟踪，并记录我已约好面试", "一条旧的确认"],
            start=1,
        )
    ]
    db.add_all(confirmations)
    db.flush()
    turn.user_message_seq = confirmations[0].seq
    other_turn.user_message_seq = 1
    db.add_all([turn, other_turn])
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
            completed_at=NOW,
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
                        "description_plain": "Build reliable backend platforms.",
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
        "capture_job_description": ToolEffect.INTERNAL_WRITE,
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
        ("capture_job_description", "请保存这份岗位描述", True),
        ("capture_job_description", "Update this job description for me", True),
        ("capture_job_description", "不要保存这份岗位描述", False),
        ("capture_job_description", "分析这份岗位描述", False),
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
    assert "job_opportunity" in tracked, tracked
    opportunity_id = tracked["job_opportunity"]["id"]
    assert tracked["job_description_capture"] == "captured"
    assert tracked["job_description_snapshot"]["version"] == 1
    assert tracked["job_description_snapshot"]["canonical_content"] == (
        "Build reliable backend platforms."
    )
    jobs = client.get("/api/v1/career-process/opportunities")
    assert jobs.status_code == 200
    assert jobs.json()[0]["external_job_id"] == "job-42"

    career_db.add(
        AgentToolCall(
            call_id="call-read-jd-v2",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=owner.id,
            tool_name="read_url",
            effect="read",
            arguments_json={"url": "https://jobs.example.test/42"},
            timeout_seconds=20,
            status="completed",
            completed_at=NOW + timedelta(hours=1),
            policy_decision="allow",
            policy_reason="read_allowed",
            result_json={
                "url": "https://jobs.example.test/42",
                "content": "Build reliable backend and distributed platforms.",
                "provider": "example-co",
            },
        )
    )
    career_db.commit()
    captured = _call(
        "capture_job_description",
        {
            "opportunity_id": opportunity_id,
            "source_call_id": "call-read-jd-v2",
            "original_url": "https://jobs.example.test/42",
            "observed_at": (NOW + timedelta(hours=1)).isoformat(),
            "confirmation_message_id": confirmations[0].id,
            "idempotency_key": "capture-jd-v2",
        },
        ctx,
    )
    assert captured["job_description_snapshot"]["version"] == 2
    assert captured["job_description_snapshot"]["source_kind"] == "tool_result"

    advanced = _call(
        "record_career_event",
        {
            "opportunity_id": opportunity_id,
            "kind": "interview_scheduled",
            "occurred_at": NOW.isoformat(),
            "confirmation_message_id": confirmations[0].id,
            "description": "用户确认一面已安排",
            "step_summary": "一面已安排",
            "idempotency_key": "event-interview-42",
            "next_action": {
                "content": "参加一面",
                "time_kind": "fixed",
                "starts_at": (NOW + timedelta(days=2)).isoformat(),
                "ends_at": (NOW + timedelta(days=2, hours=1)).isoformat(),
                "original_time_text": "8 月 15 日 17:00",
                "source_timezone": "Asia/Shanghai",
                "reminder_at": (NOW + timedelta(days=1, hours=23)).isoformat(),
                "reminder_channel": "in_app",
                "idempotency_key": "action-interview-42",
            },
        },
        ctx,
    )
    assert advanced["next_action"]["source_identity"] == advanced["process_event"]["id"]
    assert advanced["next_action"]["status"] == "planned"
    assert advanced["next_action"]["planned_source_kind"] == "process_event"
    assert client.get("/api/v1/career-process/next-actions").json()[0]["content"] == (
        "参加一面"
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


def test_save_artifact_promotes_exact_conversation_attachment_without_text_copy(
    monkeypatch,
    career_db,
):
    from app.agent_runtime.tools import career as career_tools

    (
        owner,
        other,
        conversation,
        other_conversation,
        turn,
        other_turn,
        _confirmations,
    ) = _seed(career_db)
    checksum = "a" * 64
    asset = FileAsset(
        id="fa-agent-promotion",
        user_id=owner.id,
        purpose="knowledge_document",
        original_filename="portfolio.pdf",
        object_key=f"uploads/{owner.id}/fa-agent-promotion/portfolio.pdf",
        storage_uri=f"s3://bucket/uploads/{owner.id}/fa-agent-promotion/portfolio.pdf",
        content_type="application/pdf",
        size_bytes=100,
        checksum_sha256=checksum,
        upload_status="uploaded",
        validation_status="passed",
    )
    document = KnowledgeDocument(
        id="doc-agent-promotion",
        user_id=owner.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title="portfolio.pdf",
        category="对话附件",
        source_kind="chat_attachment",
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status="ready",
        content_text="must not be copied",
    )
    ref = ConversationAttachmentRef(
        id="caref-agent-promotion",
        draft_id="draft-agent-promotion",
        user_id=owner.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="submission-agent-promotion",
        position=0,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version=f"sha256:{checksum}",
        display_name="portfolio.pdf",
    )
    career_db.add(asset)
    career_db.flush()
    career_db.add(document)
    career_db.flush()
    career_db.add(ref)
    career_db.commit()
    monkeypatch.setattr(
        career_tools,
        "SessionLocal",
        lambda: _NoCloseSession(career_db),
    )
    ctx = AgentToolContext(
        user_id=owner.username,
        user_pk=owner.id,
        session_id=conversation.id,
        turn_id=turn.id,
    )
    payload = {
        "operation_key": "agent-promote-attachment",
        "artifact_kind": "portfolio",
        "title": "项目作品集",
        "attachment_ref_id": ref.id,
    }

    first = _call("save_artifact", payload, ctx)
    replay = _call("save_artifact", payload, ctx)

    assert replay["artifact"]["id"] == first["artifact"]["id"]
    assert first["attachment_promotion"] == {
        "source_ref_id": ref.id,
        "file_asset_id": asset.id,
        "file_asset_version": ref.file_asset_version,
        "copied_parsed_text": False,
        "external_action_performed": False,
    }
    version = (
        career_db.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == first["artifact"]["id"])
        .one()
    )
    assert version.content_text is None
    assert version.file_asset_id == asset.id
    assert version.file_asset_version == ref.file_asset_version
    assert version.source_owner_type == "conversation_attachment_ref"
    assert ref.removed_at is None

    other_ctx = AgentToolContext(
        user_id=other.username,
        user_pk=other.id,
        session_id=other_conversation.id,
        turn_id=other_turn.id,
    )
    denied = _call(
        "save_artifact",
        {**payload, "operation_key": "cross-tenant-attachment"},
        other_ctx,
    )
    assert denied == {"error": "not_found_or_not_owned"}
    invalid_copy = _call(
        "save_artifact",
        {**payload, "content_text": "do not copy this projection"},
        ctx,
    )
    assert invalid_copy["error"] == "tool_args_validation_failed"


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
    with pytest.raises(
        ValueError,
        match="confirmation_message_is_not_current_turn_user_message",
    ):
        _call(
            "track_search_job",
            {
                "search_call_id": "call-search-1",
                "job_id": "job-42",
                "confirmation_message_id": confirmations[1].id,
                "occurred_at": NOW.isoformat(),
                "idempotency_key": "stale-confirmation",
            },
            owner_ctx,
        )
    with pytest.raises(
        ValueError,
        match="confirmation_message_is_not_current_turn_user_message",
    ):
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
