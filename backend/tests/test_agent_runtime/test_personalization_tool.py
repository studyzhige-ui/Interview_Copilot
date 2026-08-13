from __future__ import annotations

import asyncio

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.interview_record import InterviewRecord
from app.models.user import User


class _NoCloseSession:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass


def _seed(db, *, debrief: bool = False):
    user = User(
        username="guidance-user", email="guidance@example.test", hashed_password="x"
    )
    db.add(user)
    db.flush()
    interview = None
    if debrief:
        interview = InterviewRecord(user_id=user.id, source="upload", title="Interview")
        db.add(interview)
        db.flush()
    conversation = Conversation(
        user_id=user.id,
        mode="agent",
        type="debrief" if debrief else "general",
        subject_type="interview_record" if debrief else None,
        subject_id=interview.id if interview else None,
    )
    db.add(conversation)
    db.flush()
    current = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="user",
        content="以后默认先给结论",
    )
    old = ConversationMessage(
        conversation_id=conversation.id,
        seq=2,
        role="user",
        content="旧消息",
    )
    db.add_all([current, old])
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message=current.content,
        user_message_seq=current.seq,
        status="running",
    )
    db.add(turn)
    db.commit()
    return (
        user,
        conversation,
        interview,
        current,
        old,
        AgentToolContext(
            user_id=user.username,
            user_pk=user.id,
            session_id=conversation.id,
            turn_id=turn.id,
        ),
    )


def _dispatch(payload, ctx):
    return asyncio.run(
        registry.dispatch("manage_personalization_guidance", payload, ctx)
    )


def test_personalization_tool_surface_and_scope_authorization():
    definition = registry.get("manage_personalization_guidance")
    assert definition is not None
    assert definition.effect is ToolEffect.INTERNAL_WRITE
    ctx = AgentToolContext("u", "conversation", "turn", 1)
    cases = [
        ("set_conversation", "请让这个对话都先给结论", True),
        ("set_debrief", "本次复盘都请逐题反馈", True),
        ("add_global_rule", "以后默认先给结论", True),
        ("add_global_rule", "如何设置默认回答方式", False),
        ("add_global_rule", "不要记住以后默认先给结论", False),
        ("set_debrief", "请让这个对话都简短回答", False),
    ]
    for operation, task, expected in cases:
        authorized, reversible = registry.policy_traits(
            "manage_personalization_guidance",
            {"operation": operation},
            ctx,
            task,
        )
        assert authorized is expected
        assert reversible is False


def test_global_rule_requires_current_turn_and_preserves_existing_rules(
    monkeypatch,
    db_session,
):
    from app.agent_runtime.tools import personalization

    monkeypatch.setattr(
        personalization, "SessionLocal", lambda: _NoCloseSession(db_session)
    )
    _user, _conversation, _interview, current, old, ctx = _seed(db_session)
    created = _dispatch(
        {
            "operation": "add_global_rule",
            "expected_version": 0,
            "source_message_id": current.id,
            "rule": "先给结论",
        },
        ctx,
    )
    assert created["owner"] == "copilot_preference"
    assert created["state"]["instructions"] == ["先给结论"]

    rejected = _dispatch(
        {
            "operation": "add_global_rule",
            "expected_version": 1,
            "source_message_id": old.id,
            "rule": "不应写入",
        },
        ctx,
    )
    assert rejected["error"] == "current_task_confirmation_required"


def test_debrief_guidance_uses_current_interview_owner(monkeypatch, db_session):
    from app.agent_runtime.tools import personalization

    monkeypatch.setattr(
        personalization, "SessionLocal", lambda: _NoCloseSession(db_session)
    )
    _user, conversation, interview, current, _old, ctx = _seed(db_session, debrief=True)
    result = _dispatch(
        {
            "operation": "set_debrief",
            "expected_version": 0,
            "source_message_id": current.id,
            "guidance": "逐题即时反馈",
        },
        ctx,
    )
    db_session.refresh(interview)

    assert result["owner"] == "interview_record"
    assert result["state"]["owner_id"] == interview.id
    assert interview.debrief_guidance_text == "逐题即时反馈"
    assert conversation.guidance_text is None
