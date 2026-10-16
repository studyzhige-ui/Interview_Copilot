"""Dispatch projections cannot bypass owner controls through checkpoint replay."""

import copy
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.conversation import context_store, context_window
from app.conversation.context_contracts import AssembledContext
from app.conversation.context_manager import finish
from app.core.model_provider_adapter import ModelProviderAdapter, ProviderStreamEvent
from app.models.chat import Conversation
from app.models.context_checkpoint import ContextCheckpoint
from app.models.conversation_turn import ConversationTurn


@pytest.fixture
def checkpoint_db(db, owners, monkeypatch):
    conversation = Conversation(id="checkpoint-test", user_id=owners[0].id)
    db.add(conversation)
    db.flush()
    monkeypatch.setattr(
        context_store,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), join_transaction_mode="create_savepoint"),
    )
    return conversation


def test_runtime_plan_is_replaced_not_accumulated_or_resurrected():
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    anchor = context_window.item({"role": "user", "content": "original task"}, "user")
    reducer = ActiveTurnContextReducer(
        SimpleNamespace(context_window=16000, max_output_tokens=1000),
        task_anchor=anchor,
    )
    messages = [anchor]
    reducer.update_runtime_state(messages, "phase 1 running")
    reducer.update_runtime_state(messages, "phase 2 running")
    assert len(messages) == 2
    assert "phase 1" not in str(messages)
    original = copy.deepcopy(messages)
    reducer.update_runtime_state(messages, "phase 2 running")
    assert messages == original
    reducer.update_runtime_state(messages, "")
    assert messages == [anchor]
    assert "phase" not in str(reducer._restore_task([]))


@pytest.mark.asyncio
async def test_completed_checkpoint_replays_dialogue_without_revocable_slots(
    checkpoint_db,
):
    messages = [
        context_window.item(
            {"role": "user", "content": "private recalled memory"}, "memory_block"
        ),
        context_window.item(
            {"role": "user", "content": "old preference"}, "personalization_guidance"
        ),
        context_window.item(
            {"role": "user", "content": "old job status"}, "product_object_context"
        ),
        {"role": "runtime", "content": "old execution state"},
        context_window.item({"role": "user", "content": "compare"}, "user"),
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "private reasoning",
        },
    ]
    original = copy.deepcopy(messages)
    assembled = AssembledContext(conversation_id=checkpoint_db.id)
    await finish(assembled, messages=messages, through_seq=2)
    restored = context_store.load(checkpoint_db.id)
    assert restored["through_seq"] == 2 and assembled.checkpoint_version == 1
    assert [m["content"] for m in restored["state"]["messages"]] == [
        "compare",
        "answer",
    ]
    assert "reasoning_content" not in restored["state"]["messages"][-1]
    assert messages == original
    # A late writer cannot republish an older projection.
    assert (
        context_store.save(
            checkpoint_db.id, expected_version=0, through_seq=3, state={"messages": []}
        )
        is None
    )


def test_legacy_summary_is_rebuilt_without_resetting_version_fence(db, checkpoint_db):
    db.add(
        ContextCheckpoint(
            conversation_id=checkpoint_db.id,
            scope="",
            version=7,
            through_seq=20,
            window_id="legacy",
            state={
                "messages": [
                    context_window.item(
                        {"role": "user", "content": "paraphrased forgotten memory"},
                        "summary",
                    )
                ]
            },
        )
    )
    db.flush()
    restored = context_store.load(checkpoint_db.id)
    assert restored["through_seq"] == 0
    assert restored["state"]["messages"] == []
    assert restored["version"] == 7
    saved = context_store.save(
        checkpoint_db.id, expected_version=7, through_seq=20, state={"messages": []}
    )
    assert saved["version"] == 8


@pytest.mark.parametrize(
    "reason", ["cancelled", "cancel_requested", "generation", "owner"]
)
def test_late_compaction_cannot_publish_after_turn_authority_changes(
    db, owners, checkpoint_db, reason
):
    turn = ConversationTurn(
        id="checkpoint-turn",
        conversation_id=checkpoint_db.id,
        user_id=checkpoint_db.user_id,
        mode="agent",
        message="task",
        status="running",
        dispatch_generation=1,
    )
    db.add(turn)
    db.flush()
    if reason == "cancelled":
        turn.status = "cancelled"
    elif reason == "cancel_requested":
        turn.cancel_requested = True
    elif reason == "generation":
        turn.dispatch_generation = 2
    else:
        turn.user_id = owners[1].id
    db.flush()
    assert (
        context_store.save(
            checkpoint_db.id,
            expected_version=0,
            through_seq=2,
            state={"messages": [{"role": "user", "content": "late summary"}]},
            turn_id=turn.id,
            dispatch_generation=1,
        )
        is None
    )
    assert context_store.load(checkpoint_db.id) is None


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_turn_reclaims_only_its_inflight_checkpoint(
    db, checkpoint_db, monkeypatch, status
):
    from app.conversation.application import turn_store

    # SQLite's legacy savepoint behavior otherwise commits the shared fixture.
    monkeypatch.setattr(db, "commit", db.flush)
    monkeypatch.setattr(
        turn_store, "_admit_persistent_task_after_user_terminal", lambda *a, **kw: None
    )
    turn = ConversationTurn(
        id="terminal-turn",
        conversation_id=checkpoint_db.id,
        user_id=checkpoint_db.user_id,
        mode="agent",
        message="task",
        status="running",
    )
    db.add(turn)
    for scope in ("", turn.id, "another-turn"):
        db.add(
            ContextCheckpoint(
                conversation_id=checkpoint_db.id,
                scope=scope,
                window_id=scope or "completed",
                state={"format_version": 2, "messages": []},
            )
        )
    db.flush()
    changed, _ = turn_store._terminalize(
        db, turn.id, allowed_statuses={"running"}, status=status, error=None
    )
    assert changed
    assert {row.scope for row in db.query(ContextCheckpoint).all()} == {
        "",
        "another-turn",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["stop", "length", None])
async def test_summary_never_ingests_revocable_material(monkeypatch, stop):
    captured = []

    async def stream(self, request):
        captured.append(request)

        async def events():
            yield ProviderStreamEvent(text_delta="historical summary", stop_reason=stop)

        return events()

    monkeypatch.setattr(ModelProviderAdapter, "start_stream", stream)
    monkeypatch.setattr(context_window.settings, "CONTEXT_RECENT_TOKENS", 0)
    messages = [
        {"role": "system", "content": "rules"},
        context_window.item(
            {"role": "user", "content": "secret-memory-marker"}, "memory_block"
        ),
        context_window.item(
            {"role": "user", "content": "old-guidance-marker"},
            "personalization_guidance",
        ),
        {"role": "user", "content": "original task"},
        {"role": "assistant", "content": "historical answer"},
    ]
    original = copy.deepcopy(messages)
    arguments = dict(
        client=object(),
        profile=SimpleNamespace(
            context_window=16000, max_output_tokens=1000, model="test"
        ),
        output_tokens=1000,
    )
    if stop == "stop":
        result, report = await context_window.compact(messages, **arguments)
        assert report["status"] == "completed"
        assert any(context_window.kind(m) == "summary" for m in result)
    else:
        with pytest.raises(context_window.ContextCapacityError):
            await context_window.compact(messages, **arguments)
    assert "secret-memory-marker" not in str(captured)
    assert "old-guidance-marker" not in str(captured)
    assert "original task" in str(captured)
    assert messages == original
