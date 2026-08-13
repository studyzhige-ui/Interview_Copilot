from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.models.agent_task import AgentTask
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User


class _NoCloseSession:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        self._inner.commit()


def _seed(db_session):
    user = User(
        username=f"task-tool-{uuid.uuid4().hex}",
        hashed_password="test-hash",
    )
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, mode="agent")
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="complete a complex request",
        status="running",
    )
    db_session.add(turn)
    db_session.flush()
    return user, conversation, turn


def _create_payload():
    return {
        "objective": "Compare options and deliver a recommendation",
        "completion_conditions": ["Comparison and delivery are complete"],
        "phases": [
            {"id": "compare", "title": "Compare options", "status": "in_progress"},
            {"id": "deliver", "title": "Deliver result", "status": "pending"},
        ],
        "idempotency_key": "create-call-1",
    }


def test_agent_task_tools_are_narrow_typed_runtime_controls():
    for name in ("task_create", "task_update"):
        definition = registry.get(name)
        assert definition is not None
        assert definition.effect is ToolEffect.RUNTIME_CONTROL
        assert definition.concurrency_safe is False

    create_schema = next(
        schema
        for schema in registry.get_openai_schemas()
        if schema["function"]["name"] == "task_create"
    )["function"]["parameters"]
    assert "$defs" in create_schema
    assert create_schema["properties"]["phases"]["items"]["$ref"].startswith("#/$defs/")
    assert "title" in create_schema["$defs"]["AgentTaskPhase"]["properties"]
    assert set(create_schema["$defs"]["AgentTaskPhase"]["required"]) == set(
        create_schema["$defs"]["AgentTaskPhase"]["properties"]
    )


def test_agent_task_tools_create_and_cas_update_current_turn(
    monkeypatch,
    db_session,
):
    from app.agent_runtime.tools import agent_task as task_tool

    user, conversation, turn = _seed(db_session)
    monkeypatch.setattr(
        task_tool,
        "SessionLocal",
        lambda: _NoCloseSession(db_session),
    )
    ctx = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
    )

    created = asyncio.run(registry.dispatch("task_create", _create_payload(), ctx))
    assert created["agent_task"]["turn_id"] == turn.id
    assert created["agent_task"]["version"] == 1

    updated = asyncio.run(
        registry.dispatch(
            "task_update",
            {
                **{
                    key: value
                    for key, value in _create_payload().items()
                    if key != "idempotency_key"
                },
                "phases": [
                    {
                        "id": "compare",
                        "title": "Compare options",
                        "status": "completed",
                        "result_refs": [
                            {"owner": "tool_call", "identity": "call-search"}
                        ],
                    },
                    {
                        "id": "deliver",
                        "title": "Deliver result",
                        "status": "completed",
                    },
                ],
                "expected_version": 1,
                "idempotency_key": "update-call-1",
                "reason": "Both phases are complete",
            },
            ctx,
        )
    )
    assert updated["agent_task"]["version"] == 2
    assert all(
        phase["status"] == "completed" for phase in updated["agent_task"]["phases"]
    )
    assert db_session.query(AgentTask).filter_by(turn_id=turn.id).count() == 1


def test_agent_task_tool_requires_current_turn_scope():
    with pytest.raises(ValueError, match="agent_task_runtime_scope_unavailable"):
        asyncio.run(
            registry.dispatch(
                "task_create",
                _create_payload(),
                AgentToolContext(user_id="alice", session_id="conversation"),
            )
        )


def test_completion_gate_checks_only_current_plan_and_unresolved_tool_calls(
    monkeypatch,
    db_session,
):
    from app.conversation import engine as conversation_engine
    from app.schemas.agent_task import CreateAgentTaskRequest
    from app.services.chat.agent_task_service import create_agent_task

    user, conversation, turn = _seed(db_session)
    create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=CreateAgentTaskRequest.model_validate(_create_payload()),
    )
    monkeypatch.setattr(
        "app.db.database.SessionLocal",
        lambda: _NoCloseSession(db_session),
    )
    assert conversation_engine.check_turn_completion(turn.id, user.id) == (
        False,
        "agent_task_incomplete",
    )

    task = db_session.query(AgentTask).filter_by(turn_id=turn.id).one()
    task.phases_json = [
        {"id": "compare", "title": "Compare options", "status": "completed"},
        {"id": "deliver", "title": "Deliver result", "status": "skipped"},
    ]
    db_session.add(
        AgentToolCall(
            call_id="call-running",
            turn_id=turn.id,
            session_id=conversation.id,
            user_id=user.id,
            tool_name="search_jobs",
            effect="read",
            arguments_json={},
            timeout_seconds=10,
            status="running",
            policy_decision="allow",
            policy_reason="read_allowed",
        )
    )
    db_session.flush()
    assert conversation_engine.check_turn_completion(turn.id, user.id) == (
        False,
        "unresolved_tool_calls",
    )

    db_session.query(AgentToolCall).filter_by(call_id="call-running").update(
        {"status": "completed"}
    )
    db_session.flush()
    assert conversation_engine.check_turn_completion(turn.id, user.id) == (True, None)
