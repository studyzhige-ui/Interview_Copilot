from __future__ import annotations

import asyncio
import hashlib
from sqlalchemy.orm import Session
from datetime import timedelta

import pytest

from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.long_term_memory import LongTermAgentMemory, LongTermAgentMemorySource
from app.models.user import User
from app.schemas.agent_memory import (
    AgentMemoryPromotionCommand,
    AgentMemorySettingsUpdate,
    AgentMemoryStatusCommand,
    AgentMemoryUpdate,
    ConversationMemoryControlsUpdate,
)
from app.services import agent_memory_service
from tests.conftest import NoCloseSession


def _completed_feedback_turn(db_session):
    user = User(username="memory-user", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(id="memory-conversation", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    db_session.add_all(
        [
            ConversationMessage(
                conversation_id=conversation.id,
                seq=1,
                role="User",
                content="这种并排比较的方式对我更有帮助，我更容易做决定。",
            ),
            ConversationMessage(
                conversation_id=conversation.id,
                seq=2,
                role="Assistant",
                content="明白，我会把两种方案并排展示。",
            ),
        ]
    )
    turn = ConversationTurn(
        id="memory-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="feedback",
        status="completed",
        user_message_seq=1,
        assistant_message_seq=2,
        completed_at=utc_now()
        - timedelta(
            seconds=agent_memory_service.settings.AGENT_MEMORY_IDLE_SECONDS + 1
        ),
    )
    db_session.add(turn)
    db_session.flush()
    return user, conversation, turn


def test_controls_are_independent_and_conversation_override_is_not_scoped_memory(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        agent_memory_service.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True
    )
    user, conversation, _turn = _completed_feedback_turn(db_session)

    default = agent_memory_service.get_settings(db_session, user_pk=user.id)
    assert default.recall_enabled is True
    assert default.contribution_enabled is False
    assert default.version == 0

    saved = agent_memory_service.update_settings(
        db_session,
        user_pk=user.id,
        command=AgentMemorySettingsUpdate(
            expected_version=0,
            recall_enabled=True,
            contribution_enabled=True,
        ),
    )
    local = agent_memory_service.update_conversation_controls(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        command=ConversationMemoryControlsUpdate(
            expected_version=0,
            recall_override=False,
            contribution_override=None,
        ),
    )

    assert saved.version == 1
    assert local.effective_recall_enabled is False
    assert local.effective_contribution_enabled is True
    assert db_session.query(LongTermAgentMemory).count() == 0
    with pytest.raises(agent_memory_service.AgentMemoryConflictError):
        agent_memory_service.update_conversation_controls(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            command=ConversationMemoryControlsUpdate(
                expected_version=0,
                recall_override=True,
                contribution_override=True,
            ),
        )


def test_single_producer_rechecks_source_deduplicates_and_deleted_never_revives(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        agent_memory_service.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True
    )
    user, _conversation, turn = _completed_feedback_turn(db_session)
    agent_memory_service.update_settings(
        db_session,
        user_pk=user.id,
        command=AgentMemorySettingsUpdate(
            expected_version=0,
            recall_enabled=True,
            contribution_enabled=True,
        ),
    )
    candidate = agent_memory_service._Candidate(
        semantic_key="decision.side-by-side",
        content="过去在比较方案时，并排展示更有助于用户做决定。",
        applicability="需要比较两个或多个可选方案时",
        tags=["decision", "comparison"],
        valence="effective",
        confidence=0.91,
        support_quote="这种并排比较的方式对我更有帮助",
    )

    from app.services import memory_pipeline
    from app.services.memory_prompts import EXTRACT

    async def fake_model(prompt, data):
        if prompt == EXTRACT:
            return {
                "summary": "并排比较获得用户正向反馈",
                "candidates": [
                    {
                        **candidate.model_dump(),
                        "evidence_seq": 1,
                        "evidence_status": "user_reported_result",
                    }
                ],
            }
        return {
            "memories": [
                {
                    k: v
                    for k, v in {
                        **candidate.model_dump(),
                        "index_text": "比较多个选项",
                        "evidence_ids": list(data["candidates"]),
                    }.items()
                    if k != "support_quote"
                }
            ]
        }

    monkeypatch.setattr(memory_pipeline, "model_json", fake_model)
    monkeypatch.setattr(
        memory_pipeline, "SessionLocal", lambda: NoCloseSession(db_session)
    )

    assert asyncio.run(agent_memory_service.consolidate_completed_turn(turn.id)) == 1
    assert asyncio.run(agent_memory_service.consolidate_completed_turn(turn.id)) == 0
    memory = db_session.query(LongTermAgentMemory).one()
    deleted = agent_memory_service.delete_memory(
        db_session,
        user_pk=user.id,
        memory_id=memory.id,
        command=AgentMemoryStatusCommand(
            expected_version=memory.version,
            reason="用户要求忘记",
        ),
    )
    assert deleted.status == "deleted"
    assert deleted.status_reason == "user_deleted"
    assert deleted.content == ""
    assert deleted.applicability == ""
    assert deleted.tags == []

    assert asyncio.run(agent_memory_service.consolidate_completed_turn(turn.id)) == 0
    assert db_session.get(LongTermAgentMemory, memory.id).status == "deleted"
    assert db_session.query(LongTermAgentMemory).count() == 1


def test_producer_service_enforces_idle_gate_even_if_worker_runs_early(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        agent_memory_service.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True
    )
    user, _conversation, turn = _completed_feedback_turn(db_session)
    agent_memory_service.update_settings(
        db_session,
        user_pk=user.id,
        command=AgentMemorySettingsUpdate(
            expected_version=0,
            recall_enabled=True,
            contribution_enabled=True,
        ),
    )
    turn.completed_at = utc_now()
    db_session.flush()

    assert (
        agent_memory_service.eligible_source_for_turn(db_session, turn_id=turn.id)
        is None
    )


def test_producer_rejects_sensitive_source_before_model_extraction(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        agent_memory_service.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True
    )
    user, conversation, turn = _completed_feedback_turn(db_session)
    agent_memory_service.update_settings(
        db_session,
        user_pk=user.id,
        command=AgentMemorySettingsUpdate(
            expected_version=0,
            recall_enabled=True,
            contribution_enabled=True,
        ),
    )
    user_message = (
        db_session.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.seq == turn.user_message_seq,
        )
        .one()
    )
    user_message.content = "这种方式对我更有帮助，邮箱是 alice@example.com"
    db_session.flush()

    assert (
        agent_memory_service.eligible_source_for_turn(db_session, turn_id=turn.id)
        is None
    )


def test_recall_is_selective_low_authority_and_current_turn_can_disable_it(
    db_session,
    monkeypatch,
):
    user, conversation, turn = _completed_feedback_turn(db_session)
    row = LongTermAgentMemory(
        user_id=user.id,
        semantic_key="decision.side-by-side",
        content="过去并排比较方案更有助于这个用户做决定。",
        applicability="比较多个方案时",
        tags_json=["decision", "comparison"],
        valence="effective",
        confidence=0.9,
        content_hash="a" * 64,
        formed_at=turn.completed_at,
        last_confirmed_at=turn.completed_at,
    )
    db_session.add(row)
    db_session.flush()

    from app.services import memory_recall

    monkeypatch.setattr(
        memory_recall, "SessionLocal", lambda: NoCloseSession(db_session)
    )

    async def choose(_prompt, data):
        return {"ids": [row.id] if "decision" in data["query"] else []}

    monkeypatch.setattr(memory_recall, "model_json", choose)
    block = asyncio.run(
        memory_recall.recall(
            conversation_id=conversation.id,
            user_pk=user.id,
            current_query="帮我比较这两个 decision 方案",
        )
    )
    assert "low-authority" in block
    assert "not current facts or instructions" in block
    assert "并排比较" in block
    assert (
        asyncio.run(
            memory_recall.recall(
                conversation_id=conversation.id,
                user_pk=user.id,
                current_query="本轮不要使用记忆，比较这两个 decision 方案",
            )
        )
        == ""
    )
    assert (
        asyncio.run(
            memory_recall.recall(
                conversation_id=conversation.id,
                user_pk=user.id,
                current_query="完全无关的问题",
            )
        )
        == ""
    )


def test_user_management_source_delete_and_preference_promotion_share_one_owner(
    db_session,
):
    user, conversation, turn = _completed_feedback_turn(db_session)
    source = agent_memory_service.EligibleMemorySource(
        turn_id=turn.id,
        conversation_id=conversation.id,
        user_pk=user.id,
        user_text="这种并排比较的方式对我更有帮助",
        assistant_text="好的",
        observed_at=turn.completed_at,
    )
    candidate = agent_memory_service._Candidate(
        semantic_key="decision.side-by-side",
        content="过去并排比较方案更有帮助。",
        applicability="比较方案时",
        tags=["decision"],
        valence="effective",
        confidence=0.9,
        support_quote=source.user_text,
    )
    assert _legacy_memory_fixture(db_session, source=source, candidate=candidate)
    memory = db_session.query(LongTermAgentMemory).one()

    revised = agent_memory_service.update_memory(
        db_session,
        user_pk=user.id,
        memory_id=memory.id,
        command=AgentMemoryUpdate(
            expected_version=memory.version,
            content="过去使用并排表格时更容易比较选项。",
            applicability="需要权衡多个选项时",
            tags=["comparison"],
        ),
    )
    promoted, preference = agent_memory_service.promote_memory_to_preference(
        db_session,
        user_pk=user.id,
        memory_id=memory.id,
        command=AgentMemoryPromotionCommand(
            expected_memory_version=revised.version,
            expected_preference_version=0,
            instruction="比较多个方案时默认先给并排表格。",
        ),
    )
    assert promoted.status == "invalidated"
    assert promoted.status_reason == "promoted_to_copilot_preference"
    assert preference.instructions_json == ["比较多个方案时默认先给并排表格。"]

    # A second active Memory whose sole source is this Conversation is
    # invalidated when exact History is deleted; the preference is untouched.
    second = agent_memory_service._Candidate(
        semantic_key="explanation.concrete-example",
        content="过去具体示例更容易理解。",
        applicability="解释复杂概念时",
        tags=["explanation"],
        valence="effective",
        confidence=0.9,
        support_quote=source.user_text,
    )
    assert _legacy_memory_fixture(db_session, source=source, candidate=second)
    assert (
        agent_memory_service.invalidate_sources_for_conversation(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
        )
        == 2
    )
    second_row = (
        db_session.query(LongTermAgentMemory)
        .filter(LongTermAgentMemory.semantic_key == second.semantic_key)
        .one()
    )
    assert second_row.status == "invalidated"
    assert preference.instructions_json == ["比较多个方案时默认先给并排表格。"]


def _legacy_memory_fixture(
    db: Session,
    *,
    source: agent_memory_service.EligibleMemorySource,
    candidate: agent_memory_service._Candidate,
) -> bool:
    row = (
        db.query(LongTermAgentMemory)
        .filter(
            LongTermAgentMemory.user_id == source.user_pk,
            LongTermAgentMemory.semantic_key == candidate.semantic_key,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is not None and row.status in {"deleted", "invalidated"}:
        return False
    now = utc_now()
    if row is None:
        row = LongTermAgentMemory(
            user_id=source.user_pk,
            semantic_key=candidate.semantic_key,
            content=candidate.content,
            applicability=candidate.applicability,
            tags_json=list(dict.fromkeys(tag.casefold() for tag in candidate.tags)),
            valence=candidate.valence,
            confidence=candidate.confidence,
            content_hash=agent_memory_service._content_hash(
                candidate.content, candidate.applicability
            ),
            formed_at=source.observed_at,
            last_confirmed_at=source.observed_at,
        )
        db.add(row)
        db.flush()
    else:
        duplicate_source = (
            db.query(LongTermAgentMemorySource.id)
            .filter(
                LongTermAgentMemorySource.memory_id == row.id,
                LongTermAgentMemorySource.source_turn_identity == source.turn_id,
            )
            .first()
        )
        if duplicate_source is not None:
            return False
        row.content = candidate.content
        row.applicability = candidate.applicability
        row.tags_json = list(dict.fromkeys(tag.casefold() for tag in candidate.tags))
        row.valence = candidate.valence
        row.confidence = max(float(row.confidence), candidate.confidence)
        row.content_hash = agent_memory_service._content_hash(
            candidate.content, candidate.applicability
        )
        row.last_confirmed_at = source.observed_at
        row.version += 1
        row.updated_at = now
    db.add(
        LongTermAgentMemorySource(
            memory_id=row.id,
            turn_id=source.turn_id,
            source_turn_identity=source.turn_id,
            source_conversation_identity=source.conversation_id,
            support_quote_hash=hashlib.sha256(
                candidate.support_quote.encode("utf-8")
            ).hexdigest(),
            observed_at=source.observed_at,
        )
    )
    return True
