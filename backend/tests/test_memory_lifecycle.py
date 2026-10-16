"""Account-scoped memory consent is versioned, never an implicit opt-in."""

import pytest
import asyncio
import uuid
from datetime import timedelta
from sqlalchemy.orm import sessionmaker
from app.memory import lifecycle
from app.memory import consolidation, recall
from app.memory.prompts import EXTRACT, CONSOLIDATE
from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.long_term_memory import AgentMemorySetting, LongTermAgentMemory
from app.models.memory_pipeline import MemoryExtraction, MemoryReadReceipt
from app.schemas.agent_memory import AgentMemorySettingsUpdate
from app.schemas.agent_memory import AgentMemoryStatusCommand
from app.schemas.agent_memory import AgentMemoryUpdate, AgentMemoryPromotionCommand


def test_contribution_requires_explicit_owner_version_and_can_be_revoked(db, owners):
    owner, other = owners
    initial = lifecycle.get_settings(db, user_pk=owner.id)
    assert initial.contribution_enabled is False
    updated = lifecycle.update_settings(
        db,
        user_pk=owner.id,
        command=AgentMemorySettingsUpdate(
            expected_version=initial.version,
            recall_enabled=True,
            contribution_enabled=True,
        ),
    )
    assert updated.contribution_enabled and updated.version > initial.version
    assert lifecycle.get_settings(db, user_pk=other.id).contribution_enabled is False
    with pytest.raises(lifecycle.AgentMemoryConflictError):
        lifecycle.update_settings(
            db,
            user_pk=owner.id,
            command=AgentMemorySettingsUpdate(
                expected_version=initial.version,
                recall_enabled=False,
                contribution_enabled=False,
            ),
        )
    revoked = lifecycle.update_settings(
        db,
        user_pk=owner.id,
        command=AgentMemorySettingsUpdate(
            expected_version=updated.version,
            recall_enabled=False,
            contribution_enabled=False,
        ),
    )
    assert not revoked.contribution_enabled and not revoked.recall_enabled


@pytest.fixture
def pipeline(db, owners, monkeypatch):
    owner, other = owners
    identity = uuid.uuid4().hex
    quote = "使用比较表，我很快看清了方案取舍。"
    conversation = Conversation(id=identity, user_id=owner.id)
    turn = ConversationTurn(
        id=identity,
        conversation_id=identity,
        user_id=owner.id,
        mode="agent",
        message=quote,
        status="completed",
        user_message_seq=1,
        assistant_message_seq=2,
        completed_at=utc_now() - timedelta(hours=1),
    )
    db.add_all(
        [conversation, AgentMemorySetting(user_id=owner.id, contribution_enabled=True)]
    )
    db.flush()
    db.add_all(
        [
            turn,
            ConversationMessage(
                conversation_id=identity, seq=1, role="User", content=quote
            ),
            ConversationMessage(
                conversation_id=identity, seq=2, role="Assistant", content="收到反馈。"
            ),
        ]
    )
    db.flush()
    sessions = sessionmaker(
        bind=db.get_bind(), join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr(consolidation, "SessionLocal", sessions)
    monkeypatch.setattr(recall, "SessionLocal", sessions)
    monkeypatch.setattr(consolidation.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True)
    calls = []

    async def model(instruction, data):
        calls.append(instruction)
        item = dict(
            semantic_key="compare-options",
            content="比较表帮助看清取舍。",
            applicability="比较方案时",
            tags=["比较"],
            valence="effective",
            confidence=0.6,
        )
        if instruction == EXTRACT:
            return {
                "summary": "比较方式反馈",
                "candidates": [
                    {
                        **item,
                        "support_quote": quote,
                        "evidence_seq": 1,
                        "evidence_kind": "user",
                        "evidence_status": "user_reported_result",
                    }
                ],
            }
        if instruction == CONSOLIDATE:
            return {
                "memories": [
                    {
                        **item,
                        "index_text": "比较方案的取舍",
                        "evidence_ids": list(data["candidates"]),
                    }
                ]
            }
        return {"ids": [data["index"][0]["id"]]}

    monkeypatch.setattr(consolidation, "model_json", model)
    monkeypatch.setattr(recall, "model_json", model)
    return owner, other, conversation, turn, calls, model


@pytest.mark.parametrize(
    "blocked",
    ["deployment", "account", "conversation", "active", "fresh", "failed", "secret"],
)
def test_ineligible_history_never_calls_the_model(db, pipeline, monkeypatch, blocked):
    owner, _, conversation, turn, calls, _ = pipeline
    if blocked == "deployment":
        monkeypatch.setattr(
            consolidation.settings, "AGENT_MEMORY_PRODUCER_ENABLED", False
        )
    elif blocked == "account":
        db.query(AgentMemorySetting).filter_by(
            user_id=owner.id
        ).one().contribution_enabled = False
    elif blocked == "conversation":
        conversation.memory_contribution_override = False
    elif blocked == "active":
        conversation.active_turn_id = turn.id
    elif blocked == "fresh":
        turn.completed_at = utc_now()
    elif blocked == "failed":
        turn.status = "failed"
    else:
        db.query(ConversationMessage).filter_by(
            conversation_id=conversation.id, seq=1
        ).one().content = "password=synthetic-secret"
    db.flush()
    assert turn.id not in consolidation.discover_turns()
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0
    assert calls == []
    assert db.query(MemoryExtraction).count() == 0


def test_two_phase_publication_recall_isolation_and_usage(db, pipeline):
    owner, other, conversation, turn, calls, _ = pipeline
    assert turn.id in consolidation.discover_turns()
    assert asyncio.run(consolidation.process_turn(turn.id)) == 1
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0
    assert len(calls) == 2
    args = dict(
        conversation_id=conversation.id,
        user_pk=owner.id,
        turn_id=turn.id,
        current_query="比较两个方案",
    )
    block = asyncio.run(recall.recall(**args))
    assert "比较表帮助看清取舍" in block
    assert asyncio.run(recall.recall(**args))
    assert db.query(MemoryReadReceipt).count() == 1
    db.expire_all()
    memory = db.query(LongTermAgentMemory).one()
    assert memory.recall_count == 1 and memory.usage_count == 0
    before = len(calls)
    assert not asyncio.run(recall.recall(**{**args, "user_pk": other.id}))
    assert not asyncio.run(
        recall.recall(**{**args, "current_query": "本轮不要使用记忆，比较两个方案"})
    )
    conversation.memory_recall_override = False
    db.flush()
    assert not asyncio.run(recall.recall(**args)) and len(calls) == before
    message = (
        db.query(ConversationMessage)
        .filter_by(conversation_id=conversation.id, seq=2)
        .one()
    )
    message.content = f"[记忆来源](/settings/personalization#memory-{memory.id})"
    db.flush()
    recall.record_turn_usage(db, turn)
    db.flush()
    recall.record_turn_usage(db, turn)
    assert memory.usage_count == 1


@pytest.mark.parametrize(
    "change",
    ["unchanged", "edit", "disabled", "account", "conversation", "source", "expired"],
)
def test_memory_is_revalidated_on_each_agent_dispatch_and_after_compaction(
    db, pipeline, monkeypatch, change
):
    from types import SimpleNamespace
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer
    from app.agent_runtime.react_agent import AgentRunState
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.context_window import item
    from app.core.model_provider_adapter import (
        ModelProviderAdapter,
        ProviderStreamEvent,
    )

    owner, _, conversation, turn, _, _ = pipeline
    asyncio.run(consolidation.process_turn(turn.id))
    block = asyncio.run(
        recall.recall(
            conversation_id=conversation.id,
            user_pk=owner.id,
            turn_id=turn.id,
            current_query="比较两个方案",
        )
    )
    db.expire_all()
    row = db.query(LongTermAgentMemory).one()
    profile = SimpleNamespace(
        max_output_tokens=1000, context_window=16000, provider="test", model="test"
    )
    anchor = item({"role": "user", "content": "compare"}, "user")
    snapshot = item({"role": "user", "content": "[Memory]\n" + block}, "memory_block")
    compactor = ActiveTurnContextReducer(profile, task_anchor=anchor)
    compactor.assembled = SimpleNamespace(conversation_id=conversation.id)
    compactor.initial_context = [snapshot]
    messages = [{"role": "system", "content": "rules"}, snapshot, anchor]
    observed = []

    async def stream(self, request):
        observed.append(str(request.messages))

        async def events():
            yield ProviderStreamEvent(text_delta="answer", stop_reason="stop")

        return events()

    monkeypatch.setattr(ModelProviderAdapter, "start_stream", stream)

    async def dispatch():
        stream, _ = await AgentLoopStrategy()._call_llm_stream(
            client=object(),
            profile=profile,
            messages=messages,
            tool_schemas=[],
            compactor=compactor,
            budget=AgentRunState(started_at=0),
            user_pk=owner.id,
        )
        async for _ in stream:
            pass

    asyncio.run(dispatch())
    assert "比较表帮助看清取舍" in observed[-1]
    if change == "edit":
        row.version += 1
        row.content = "new version must be selected separately"
    elif change == "disabled":
        row.status = "invalidated"
    elif change == "account":
        db.query(AgentMemorySetting).filter_by(
            user_id=owner.id
        ).one().recall_enabled = False
    elif change == "conversation":
        conversation.memory_recall_override = False
    elif change == "source":
        db.get(MemoryExtraction, turn.id).status = "invalidated"
    elif change == "expired":
        db.get(MemoryExtraction, turn.id).generated_at = utc_now() - timedelta(days=100)
    db.flush()
    asyncio.run(dispatch())
    assert ("比较表帮助看清取舍" in observed[-1]) == (change == "unchanged")
    restored = compactor._restore_task([{"role": "system", "content": "rules"}])
    assert ("比较表帮助看清取舍" in str(restored)) == (change == "unchanged")
    assert "new version must be selected separately" not in observed[-1]
    # Validation is not another recall event or evidence that the memory helped.
    db.expire_all()
    assert db.query(MemoryReadReceipt).count() == 1
    assert db.query(LongTermAgentMemory).one().recall_count == 1


@pytest.mark.parametrize(
    "change", ["helpful", "unhelpful", "edited", "expired", "other_owner"]
)
def test_explicit_usefulness_affects_retention_without_inventing_citation(
    db, pipeline, change
):
    owner, other, conversation, turn, _, _ = pipeline
    asyncio.run(consolidation.process_turn(turn.id))
    asyncio.run(
        recall.recall(
            conversation_id=conversation.id,
            user_pk=owner.id,
            turn_id=turn.id,
            current_query="比较两个方案",
        )
    )
    db.expire_all()
    remembered = db.query(LongTermAgentMemory).one()
    receipt = db.query(MemoryReadReceipt).one()
    if change == "edited":
        remembered.version += 1
    elif change == "expired":
        db.get(MemoryExtraction, turn.id).generated_at = utc_now() - timedelta(days=100)
    db.flush()
    if change == "other_owner":
        with pytest.raises(lifecycle.AgentMemoryNotFoundError):
            recall.set_feedback(
                db, user_id=other.id, receipt_id=receipt.id, feedback="helpful"
            )
    else:
        for _ in range(2):
            recall.set_feedback(
                db,
                user_id=owner.id,
                receipt_id=receipt.id,
                feedback="unhelpful" if change == "unhelpful" else "helpful",
            )
    assert remembered.last_used_at == (
        receipt.created_at if change == "helpful" else None
    )
    assert remembered.usage_count == 0 and receipt.cited_at is None
    if change == "helpful":
        db.get(MemoryExtraction, turn.id).generated_at = utc_now() - timedelta(days=100)
        db.flush()
        from app.memory.retention import unavailable_memory_ids

        assert remembered.id not in unavailable_memory_ids(db, owner.id)


@pytest.mark.parametrize("forget", ["item", "source", "retention"])
def test_erasure_clears_projections_and_prevents_replay(db, pipeline, forget):
    owner, _, conversation, turn, calls, _ = pipeline
    asyncio.run(consolidation.process_turn(turn.id))
    db.expire_all()
    memory = db.query(LongTermAgentMemory).one()
    if forget == "item":
        lifecycle.delete_memory(
            db,
            user_pk=owner.id,
            memory_id=memory.id,
            command=AgentMemoryStatusCommand(
                expected_version=memory.version, reason="test"
            ),
        )
    elif forget == "source":
        lifecycle.invalidate_sources_for_conversation(
            db, user_pk=owner.id, conversation_id=conversation.id
        )
    else:
        db.get(MemoryExtraction, turn.id).generated_at = utc_now() - timedelta(days=61)
    db.flush()
    assert not asyncio.run(
        recall.recall(
            conversation_id=conversation.id,
            user_pk=owner.id,
            turn_id=turn.id,
            current_query="比较两个方案",
        )
    )
    asyncio.run(consolidation.consolidate_user(owner.id))
    before = len(calls)
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0
    assert len(calls) == before
    db.expire_all()
    memory = db.get(LongTermAgentMemory, memory.id)
    extraction = db.get(MemoryExtraction, turn.id)
    assert (
        memory.status != "active"
        and not memory.content
        and not memory.evidence_json
        and not memory.index_text
    )
    assert not extraction.candidates_json and not extraction.summary


def test_model_failure_is_retryable_and_empty_output_is_terminal(
    db, pipeline, monkeypatch
):
    _, _, _, turn, calls, _ = pipeline

    async def fail(*_):
        calls.append("failure")
        raise TimeoutError("provider response must not be persisted")

    monkeypatch.setattr(consolidation, "model_json", fail)
    with pytest.raises(TimeoutError):
        asyncio.run(consolidation.process_turn(turn.id))
    extraction = db.get(MemoryExtraction, turn.id)
    assert extraction.status == "failed" and extraction.error_code == "TimeoutError"
    assert extraction.retry_at > utc_now() and extraction.lease_token is None
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0 and len(calls) == 1
    extraction.retry_at = utc_now() - timedelta(seconds=1)
    db.flush()

    async def empty(*_):
        calls.append("empty")
        return {"summary": "", "candidates": []}

    monkeypatch.setattr(consolidation, "model_json", empty)
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0
    db.expire_all()
    assert db.get(MemoryExtraction, turn.id).status == "no_output"
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0 and len(calls) == 2


def test_contribution_revoked_during_extraction_fences_the_result(
    db, pipeline, monkeypatch
):
    owner, _, _, turn, _, model = pipeline

    async def revoke(instruction, data):
        db.query(AgentMemorySetting).filter_by(
            user_id=owner.id
        ).one().contribution_enabled = False
        db.flush()
        return await model(instruction, data)

    monkeypatch.setattr(consolidation, "model_json", revoke)
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0
    assert db.query(LongTermAgentMemory).count() == 0
    extraction = db.get(MemoryExtraction, turn.id)
    assert extraction.status == "failed" and extraction.error_code == "source_changed"


@pytest.mark.parametrize("mutation", ["edit", "promote"])
def test_user_management_cannot_be_overwritten_by_consolidation(db, pipeline, mutation):
    owner, _, _, turn, _, _ = pipeline
    asyncio.run(consolidation.process_turn(turn.id))
    db.expire_all()
    row = db.query(LongTermAgentMemory).one()
    if mutation == "edit":
        lifecycle.update_memory(
            db,
            user_pk=owner.id,
            memory_id=row.id,
            command=AgentMemoryUpdate(
                expected_version=row.version,
                content="比较表对三个以上方案更有帮助。",
                applicability="多方案权衡",
                tags=[],
            ),
        )
    else:
        _, preference = lifecycle.promote_memory_to_preference(
            db,
            user_pk=owner.id,
            memory_id=row.id,
            command=AgentMemoryPromotionCommand(
                expected_memory_version=row.version,
                expected_preference_version=0,
                instruction="比较方案时先列对比表。",
            ),
        )
        assert preference.instructions_json == ["比较方案时先列对比表。"]
    db.flush()
    assert asyncio.run(consolidation.process_turn(turn.id)) == 0
    db.expire_all()
    row = db.get(LongTermAgentMemory, row.id)
    if mutation == "edit":
        assert (
            row.origin == "manual" and row.content == "比较表对三个以上方案更有帮助。"
        )
    else:
        assert row.status == "invalidated"
        assert lifecycle.list_memories(db, user_pk=owner.id) == []


@pytest.mark.parametrize("phase", ["consolidation", "selection"])
def test_source_deletion_during_model_call_fences_publication_and_recall(
    db, pipeline, monkeypatch, phase
):
    owner, _, conversation, turn, _, model = pipeline

    async def remove_source(instruction, data):
        output = await model(instruction, data)
        if (instruction == CONSOLIDATE) == (phase == "consolidation"):
            lifecycle.invalidate_sources_for_conversation(
                db, user_pk=owner.id, conversation_id=conversation.id
            )
            db.flush()
        return output

    if phase == "consolidation":
        monkeypatch.setattr(consolidation, "model_json", remove_source)
        assert asyncio.run(consolidation.process_turn(turn.id)) == 0
        assert db.query(LongTermAgentMemory).count() == 0
    else:
        asyncio.run(consolidation.process_turn(turn.id))
        monkeypatch.setattr(recall, "model_json", remove_source)
        assert not asyncio.run(
            recall.recall(
                conversation_id=conversation.id,
                user_pk=owner.id,
                turn_id=turn.id,
                current_query="比较两个方案",
            )
        )
        assert db.query(MemoryReadReceipt).count() == 0
