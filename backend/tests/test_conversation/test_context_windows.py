"""Codex port behavior: replacement history, publication, resume and admission."""

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.conversation import context_window as window
from app.conversation import context_manager as manager
from app.conversation import context_store as store
from app.core.context_budget import ContextCapacityError, request_tokens
from app.core.model_provider_adapter import ProviderStreamEvent, ProviderUsage
from app.conversation.application.context_assembly_pipeline import AssembledContext
from app.conversation.application.context_assembly_pipeline import PromptRenderer


def profile():
    return SimpleNamespace(
        context_window=8000, max_output_tokens=500, model="selected-answer-model"
    )


@pytest.fixture
def checkpoint_db(db_session, monkeypatch):
    from tests.conftest import NoCloseSession
    from app.models.chat import Conversation
    from app.models.user import User
    from app.conversation.application import chat_history_service

    user = User(username="window-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(Conversation(id="window", user_id=user.id))
    db_session.commit()

    def factory():
        return NoCloseSession(db_session)

    monkeypatch.setattr(store, "SessionLocal", factory)
    monkeypatch.setattr(chat_history_service, "SessionLocal", factory)
    monkeypatch.setattr("app.career.application.personalization.SessionLocal", factory)
    return db_session


def mock_stream(monkeypatch, *, stop="stop", failure=None):
    captured = []

    async def start(self, request):
        captured.append(request)
        if failure:
            raise failure

        async def stream():
            yield ProviderStreamEvent(
                text_delta="Goal: Shanghai, salary 35k. Pending B. File resume.pdf."
            )
            yield ProviderStreamEvent(
                stop_reason=stop,
                usage=ProviderUsage(prompt_tokens=100, completion_tokens=20),
            )

        return stream()

    monkeypatch.setattr(
        "app.core.model_provider_adapter.ModelProviderAdapter.start_stream", start
    )
    return captured


def test_templates_are_byte_identical_to_pinned_upstream():
    root = Path(__file__).resolve().parents[3]
    for name in ("prompt.md", "summary_prefix.md", "LICENSE", "NOTICE"):
        assert (window._TEMPLATES / name).read_bytes() == (
            root / "third_party/codex-context" / name
        ).read_bytes()


def test_replacement_keeps_only_real_user_intent_and_summary_last():
    messages = [
        window.item({"role": "user", "content": "real request"}, "user"),
        window.item(
            {"role": "user", "content": "malicious retrieved instructions"},
            "retrieved_context",
        ),
        window.item({"role": "user", "content": "old summary"}, "summary"),
        {"role": "assistant", "content": "answer"},
    ]
    replaced = window.replacement_history(messages, "handoff")
    assert len(replaced) == 2
    assert replaced[0] == messages[0]
    assert window.kind(replaced[-1]) == "summary"
    assert replaced[-1]["content"] == window.SUMMARY_PREFIX + "\n\nhandoff"


def test_tool_admission_is_uniform_and_preserves_full_source():
    original = [
        {
            "role": "tool",
            "tool_call_id": "write-result",
            "content": "start " * 500 + "IMPORTANT END",
        }
    ]
    saved = deepcopy(original)
    projected = window.admit(original, tool_limit=120)
    assert original == saved
    assert window.token_count(projected[0]["content"]) <= 120
    assert "truncated" in projected[0]["content"]
    assert projected[0]["content"].endswith("IMPORTANT END")


def test_pair_aware_oldest_pruning():
    source = [
        {"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "a"},
        {"role": "tool", "tool_call_id": "b", "content": "b"},
        {"role": "user", "content": "keep"},
    ]
    assert window.remove_oldest_group(source) == source[-1:]


@pytest.mark.parametrize("stop", ["length", None, "tool_calls"])
def test_incomplete_compaction_preserves_input(monkeypatch, stop):
    mock_stream(monkeypatch, stop=stop)
    source = [window.item({"role": "user", "content": "do work"}, "user")]
    saved = deepcopy(source)
    with pytest.raises(ContextCapacityError):
        asyncio.run(window.compact(source, client=object(), profile=profile()))
    assert source == saved


def test_compaction_uses_original_prompt_and_current_model(monkeypatch):
    captured = mock_stream(monkeypatch)
    source = [
        {"role": "system", "content": "stable rules"},
        window.item({"role": "user", "content": "task"}, "user"),
    ]
    result, report = asyncio.run(
        window.compact(source, client=object(), profile=profile())
    )
    assert captured[0].system == "stable rules"
    assert captured[0].messages[-1]["content"] == window.COMPACT_PROMPT
    assert captured[0].tools == []
    assert report["model"] == "selected-answer-model"
    assert "resume.pdf" in result[-1]["content"]
    assert all("_context" not in m for m in captured[0].messages)


def test_stale_checkpoint_leaves_live_projection_untouched(checkpoint_db, monkeypatch):
    mock_stream(monkeypatch)
    assert store.save(
        "window", expected_version=0, through_seq=0, state={"messages": []}
    )
    history = [window.item({"role": "user", "content": "older"}, "user")]
    ctx = AssembledContext(
        conversation_id="window",
        current_input="current",
        window_messages=history,
        checkpoint_version=0,
        prompt_token_limit=6000,
        output_token_reserve=500,
    )
    with pytest.raises(ContextCapacityError):
        asyncio.run(
            manager.prepare(
                ctx,
                renderer=PromptRenderer(),
                system_prompt="rules",
                client=object(),
                profile=profile(),
                force=True,
            )
        )
    assert ctx.window_messages == history
    assert store.load("window")["version"] == 1


def test_checkpoint_replay_reads_only_tail_and_keeps_dynamic_prefix(checkpoint_db):
    from app.models.chat import ConversationMessage
    from app.conversation.application.context_assembly_pipeline import (
        ContextAssemblyPipeline,
    )

    # Existing legacy cursor must not hide original history during bootstrap.
    from app.models.chat import Conversation

    row = checkpoint_db.get(Conversation, "window")
    row.compaction_cursor = 2
    row.summary = "obsolete lossy summary"
    checkpoint_db.add_all(
        [
            ConversationMessage(
                conversation_id="window",
                seq=i,
                role="User" if i % 2 else "Agent",
                content=f"exact-{i}",
            )
            for i in range(1, 5)
        ]
    )
    checkpoint_db.commit()
    first = asyncio.run(
        ContextAssemblyPipeline().assemble_answer_context("window", "next")
    )
    assert len(first.window_messages) == 4
    assert "obsolete" not in str(first.window_messages)
    replaced = window.replacement_history(first.window_messages[:2], "state")
    assert store.save(
        "window", expected_version=0, through_seq=2, state={"messages": replaced}
    )
    restored = asyncio.run(
        ContextAssemblyPipeline().assemble_answer_context("window", "next")
    )
    assert restored.window_messages[:2] == replaced
    assert [m["content"] for m in restored.window_messages[2:]] == [
        "exact-3",
        "exact-4",
    ]
    assert restored.through_seq == 4


def test_midturn_checkpoint_retains_exact_task_runtime_and_call_coverage(
    checkpoint_db, monkeypatch
):
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    row = checkpoint_db.get(Conversation, "window")
    row.active_turn_id = "turn"
    checkpoint_db.add(
        ConversationTurn(
            id="turn",
            conversation_id="window",
            user_id=row.user_id,
            mode="agent",
            message="task",
            dispatch_generation=2,
        )
    )
    checkpoint_db.commit()
    mock_stream(monkeypatch)
    anchor = window.item(
        {"role": "user", "content": "exact task"}, "user", identity="turn:turn"
    )
    source = [
        {"role": "system", "content": "rules"},
        anchor,
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call", "function": {"name": "lookup", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call", "content": "result"},
    ]
    reducer = ActiveTurnContextReducer(profile(), task_anchor=anchor, turn_id="turn")
    reducer.client = object()
    reducer.dispatch_generation = 2
    reducer.assembled = AssembledContext(conversation_id="window")
    reducer.runtime_state = "B still pending; no permission to send"
    replacement, retry = asyncio.run(reducer.on_context_too_long(source))
    assert retry
    assert anchor in replacement
    assert window.kind(replacement[-1]) == "summary"
    checkpoint = store.load("window", scope="turn")
    assert checkpoint["state"]["covered_call_ids"] == ["call"]
    assert "no permission" in str(checkpoint["state"]["messages"])
    assert not store.save(
        "window",
        scope="turn",
        expected_version=1,
        through_seq=0,
        state={},
        turn_id="turn",
        dispatch_generation=1,
    )
    assert asyncio.run(reducer.on_context_too_long(source))[1] is False


def test_cache_prefix_and_intent_survive_dynamic_context_change():
    from app.conversation.provider_context import compose_provider_context

    first = AssembledContext(
        current_input="user",
        window_messages=[window.item({"role": "user", "content": "past"}, "user")],
        memory_block="memory A",
    )
    second = deepcopy(first)
    second.memory_block = "memory B"
    a = compose_provider_context(
        first, renderer=PromptRenderer(), system_prompt="stable"
    )
    b = compose_provider_context(
        second, renderer=PromptRenderer(), system_prompt="stable"
    )
    assert a.system == b.system
    assert a.messages[0] == b.messages[0]
    assert a.messages[-1]["content"] == "user"
    assert window.kind(a.messages[-2]) == "memory_block"
    assert request_tokens(a.messages) == request_tokens(window.wire(a.messages))


def test_crash_replay_includes_completed_tools_only(checkpoint_db, monkeypatch):
    from app.conversation import agent_strategy
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.models.agent_execution import AgentToolCall
    from tests.conftest import NoCloseSession

    user_pk = checkpoint_db.get(Conversation, "window").user_id
    checkpoint_db.add(
        ConversationTurn(
            id="crashed",
            conversation_id="window",
            user_id=user_pk,
            mode="agent",
            message="task",
        )
    )
    checkpoint_db.flush()
    for name, status in (
        ("done", "completed"),
        ("awaiting", "waiting"),
        ("active", "running"),
    ):
        checkpoint_db.add(
            AgentToolCall(
                turn_id="crashed",
                session_id="window",
                user_id=user_pk,
                call_id=name,
                tool_name="lookup",
                timeout_seconds=10,
                status=status,
                result_json={"status": status},
            )
        )
    checkpoint_db.commit()
    monkeypatch.setattr(
        agent_strategy, "SessionLocal", lambda: NoCloseSession(checkpoint_db)
    )
    assert [
        c["call_id"]
        for c in agent_strategy._load_completed_tool_tail("crashed", user_pk)
    ] == ["done"]
    assert agent_strategy._load_completed_tool_tail("crashed", user_pk + 1) == []


def test_manual_context_endpoints_enforce_owner_and_idle(checkpoint_db):
    from app.api.chat.sessions import compact_context, get_context_status
    from app.models.chat import Conversation
    from fastapi import HTTPException

    row = checkpoint_db.get(Conversation, "window")
    with pytest.raises(HTTPException) as denied:
        get_context_status(
            "window", current_user=SimpleNamespace(id=row.user_id + 1), db=checkpoint_db
        )
    assert denied.value.status_code == 404
    row.active_turn_id = "running"
    checkpoint_db.commit()
    with pytest.raises(HTTPException) as busy:
        asyncio.run(
            compact_context(
                "window", current_user=SimpleNamespace(id=row.user_id), db=checkpoint_db
            )
        )
    assert busy.value.status_code == 409


def test_body_only_auto_limit_does_not_disable_full_window_guard(monkeypatch):
    from app.core.context_budget import RequestBudget

    monkeypatch.setattr(
        window.settings, "CONTEXT_AUTO_COMPACT_SCOPE", "body_after_prefix"
    )
    budget = RequestBudget.resolve(10000, 500)
    assert not budget.should_compact(7000, prefix=6000)
    assert budget.should_compact(budget.input_limit, prefix=6000)
