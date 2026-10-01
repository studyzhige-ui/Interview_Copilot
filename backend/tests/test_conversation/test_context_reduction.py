"""Layered reduction: recovery, exact tail preservation and publication fences."""

import asyncio
from copy import deepcopy
import json

import pytest

from app.conversation import context_manager as manager, context_store as store
from app.conversation import context_window as window
from app.conversation.context_reduction import reduce_tool_results, tool_message
from app.core.context_budget import ContextCapacityError, request_tokens
from app.conversation.application.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
)
from tests.test_conversation import test_context_windows as base_tests

checkpoint_db = base_tests.checkpoint_db
mock_stream = base_tests.mock_stream
profile = base_tests.profile


def batch(ids, *, name="lookup", turn_id="old", size=700):
    return [
        {
            "role": "assistant",
            "content": "checking",
            "reasoning_content": "reasoning",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
                for call_id in ids
            ],
        },
        *[
            tool_message(call_id, (f"evidence-{call_id} 中文 " * size), turn_id)
            for call_id in ids
        ],
    ]


def test_aggregate_projects_medium_results_and_replays_identically(monkeypatch):
    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_BATCH_TOKENS", 1300)
    messages = batch(["a", "b", "c"], size=200)
    original = deepcopy(messages)
    assert all(window.token_count(m["content"]) < 1300 for m in messages[1:])
    reduced, report = reduce_tool_results(messages, input_limit=16000)
    assert report["saved_tokens"] > 0
    assert request_tokens(reduced[1:]) <= 1300
    assert messages == original
    assert reduced[0] == original[0]  # call IDs, args and reasoning unchanged
    assert any("source_turn_id" in m["content"] for m in reduced[1:])
    replay, second = reduce_tool_results(
        json.loads(json.dumps(reduced)), input_limit=16000
    )
    assert replay == reduced
    assert second["projected_results"] == []


def test_cumulative_eviction_protects_newest_batch_and_unrecoverable_results(
    monkeypatch,
):
    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_BATCH_TOKENS", 16000)
    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_HISTORY_TOKENS", 2000)
    messages = [*batch(["old"], size=300), *batch(["new"], size=300)]
    reduced, report = reduce_tool_results(messages, input_limit=40000)
    assert report["projected_results"] == ["agent_tool_call:old:old"]
    assert reduced[-1] == messages[-1]
    legacy = batch(["legacy"], turn_id=None)
    assert reduce_tool_results(legacy, input_limit=4000)[0] == legacy


def test_fresh_paged_reads_are_not_recursively_offloaded(monkeypatch):
    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_BATCH_TOKENS", 100)
    for name in ("read_file", "read_interaction_history"):
        messages = batch(["page"], name=name)
        assert reduce_tool_results(messages, input_limit=4000)[0] == messages


def test_admission_retains_exact_reference_and_raw_result():
    messages = batch(["huge"])
    original = deepcopy(messages)
    admitted = window.admit(messages, tool_limit=400)
    assert "read_file(" in admitted[-1]["content"]
    assert window.token_count(admitted[-1]["content"]) <= 400
    assert window.admit(admitted, tool_limit=400) == admitted
    assert messages == original


def test_compaction_summarizes_prefix_only_and_retains_complete_recent_exchange(
    monkeypatch,
):
    captured = mock_stream(monkeypatch)
    recent = [
        window.item({"role": "user", "content": "latest exact request"}, "user"),
        *batch(["fresh-a", "fresh-b"], size=2),
        {"role": "assistant", "content": "latest exact answer"},
    ]
    messages = [
        window.item({"role": "user", "content": "old constraints " * 1800}, "user"),
        {"role": "assistant", "content": "old answer"},
        *recent,
    ]
    original = deepcopy(messages)
    replaced, report = asyncio.run(
        window.compact(messages, client=object(), profile=profile())
    )
    assert window.wire(replaced[1:]) == window.wire(recent)
    assert window.kind(replaced[0]) == "summary"
    assert "fresh-a" not in str(captured[0].messages)
    assert "old constraints" in str(captured[0].messages)
    assert report["retained_messages"] == len(recent)
    assert messages == original
    assert window.normalize_tool_pairs(replaced) == replaced


def test_long_active_turn_retains_last_complete_parallel_batch(monkeypatch):
    captured = mock_stream(monkeypatch)
    monkeypatch.setattr(window.settings, "CONTEXT_RECENT_TOKENS", 400)
    recent = batch(["fresh-a", "fresh-b"], size=2)
    messages = [
        window.item({"role": "user", "content": "task"}, "user"),
        *batch(["old-a"], size=200),
        *recent,
    ]
    replaced, _ = asyncio.run(
        window.compact(messages, client=object(), profile=profile())
    )
    assert window.wire(replaced[1:]) == window.wire(recent)
    assert "old-a" in str(captured[0].messages)
    assert "fresh-a" not in str(captured[0].messages)


def test_final_budget_counts_tools_and_restored_state_before_publication(monkeypatch):
    mock_stream(monkeypatch)
    messages = [window.item({"role": "user", "content": "task"}, "user")]
    original = deepcopy(messages)
    with pytest.raises(ContextCapacityError, match="压缩后"):
        asyncio.run(
            window.compact(
                messages,
                client=object(),
                profile=profile(),
                tool_schemas=[
                    {
                        "type": "function",
                        "function": {"name": "huge", "description": "schema " * 9000},
                    }
                ],
                finalize=lambda replacement: [
                    *replacement,
                    {"role": "user", "content": "runtime " * 1000},
                ],
            )
        )
    assert messages == original


def test_repeated_compaction_and_serialized_replay_preserve_latest_tail(monkeypatch):
    mock_stream(monkeypatch)
    messages = [
        window.item({"role": "user", "content": "original"}, "user"),
        {"role": "assistant", "content": "first answer"},
    ]
    first, _ = asyncio.run(window.compact(messages, client=object(), profile=profile()))
    second_input = json.loads(json.dumps(first)) + [
        window.item({"role": "user", "content": "new request"}, "user"),
        *batch(["next"], size=2),
        {"role": "assistant", "content": "new answer"},
    ]
    second, _ = asyncio.run(
        window.compact(second_input, client=object(), profile=profile())
    )
    assert sum(window.kind(m) == "summary" for m in second) == 1
    assert second[-1]["content"] == "new answer"
    assert second[-2] == second_input[-2]
    assert window.normalize_tool_pairs(second) == second


def test_shared_dispatch_reduces_without_llm_and_persists(checkpoint_db, monkeypatch):
    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_BATCH_TOKENS", 700)
    history = [
        window.item({"role": "user", "content": "past"}, "user"),
        *batch(["a", "b"], size=150),
    ]
    original = deepcopy(history)
    ctx = AssembledContext(
        conversation_id="window",
        current_input="current",
        window_messages=history,
        prompt_token_limit=6500,
        output_token_reserve=500,
    )
    captured = mock_stream(monkeypatch)
    projection = asyncio.run(
        manager.prepare(
            ctx,
            renderer=PromptRenderer(),
            system_prompt="rules",
            client=object(),
            profile=profile(),
        )
    )
    assert captured == []
    assert history == original
    assert ctx.checkpoint_version == 1
    assert store.load("window")["state"]["messages"] == ctx.window_messages
    assert projection.messages[: len(history)] == ctx.window_messages
    assert ctx.context_report["compaction"]["tool_reduction"]["saved_tokens"] > 0


def test_stale_lightweight_reduction_does_not_publish(checkpoint_db, monkeypatch):
    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_BATCH_TOKENS", 700)
    store.save("window", expected_version=0, through_seq=0, state={"messages": []})
    history = [
        window.item({"role": "user", "content": "past"}, "user"),
        *batch(["a", "b"], size=150),
    ]
    ctx = AssembledContext(
        conversation_id="window",
        current_input="current",
        window_messages=history,
        prompt_token_limit=6500,
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
            )
        )
    assert ctx.window_messages == history
    assert ctx.checkpoint_version == 0


def test_cross_turn_pointer_pages_exact_owned_result(checkpoint_db, monkeypatch):
    from tests.conftest import NoCloseSession
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.models.agent_execution import AgentToolCall
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.file_tool import ReadFileArgs, _read_file_sync

    owner = checkpoint_db.get(Conversation, "window").user_id
    checkpoint_db.add(
        ConversationTurn(
            id="old",
            conversation_id="window",
            user_id=owner,
            mode="agent",
            message="original",
        )
    )
    checkpoint_db.flush()
    payload = {"evidence": "exact old result 中文 " * 500}
    checkpoint_db.add(
        AgentToolCall(
            turn_id="old",
            session_id="window",
            user_id=owner,
            call_id="result",
            tool_name="lookup",
            timeout_seconds=10,
            status="completed",
            result_json=payload,
        )
    )
    checkpoint_db.commit()
    monkeypatch.setattr(
        "app.db.database.SessionLocal", lambda: NoCloseSession(checkpoint_db)
    )
    args = ReadFileArgs(
        tool_call_id="result", source_turn_id="old", offset=31, limit=101
    )
    ctx = AgentToolContext(
        user_id="owner", user_pk=owner, session_id="window", turn_id="new"
    )
    page = _read_file_sync(args, ctx)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert page["content"] == canonical[31:132]
    assert page["next_offset"] == 132
    assert page["source_turn_id"] == "old"
    for principal, session in ((owner + 1, "window"), (owner, "another")):
        denied = _read_file_sync(
            args,
            AgentToolContext(
                user_id="other", user_pk=principal, session_id=session, turn_id="new"
            ),
        )
        assert denied["error"] == "tool_result_unavailable"


def test_reconstructed_tool_blocks_keep_source_identity():
    from app.conversation.provider_context import reconstruct_history_messages
    from app.conversation.application.context_assembly_pipeline import (
        ContextAssemblyPipeline,
    )

    turns = [
        {"role": "User", "seq": 1, "content": "question"},
        {
            "role": "Agent",
            "seq": 2,
            "content": "answer",
            "turn_id": "old",
            "blocks": [
                {"type": "tool_use", "id": "call", "name": "lookup", "input": {}},
                {"type": "tool_result", "tool_use_id": "call", "content": "result"},
            ],
        },
    ]
    messages = reconstruct_history_messages(ContextAssemblyPipeline._sanitize(turns))
    assert messages[-1]["_context"]["source_turn_id"] == "old"
    assert messages[-1]["_context"]["id"] == "agent_tool_call:old:call"


def test_active_reduction_checkpoint_covers_retained_calls_and_survives_resume(
    checkpoint_db, monkeypatch
):
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn

    monkeypatch.setattr(window.settings, "CONTEXT_TOOL_BATCH_TOKENS", 700)
    owner = checkpoint_db.get(Conversation, "window").user_id
    checkpoint_db.add(
        ConversationTurn(
            id="active",
            conversation_id="window",
            user_id=owner,
            mode="agent",
            message="task",
            dispatch_generation=2,
        )
    )
    checkpoint_db.commit()
    anchor = window.item(
        {"role": "user", "content": "exact task"}, "user", identity="turn:active"
    )
    messages = [
        {"role": "system", "content": "rules"},
        anchor,
        *batch(["a", "b"], turn_id="active", size=150),
    ]
    original = deepcopy(messages)
    reducer = ActiveTurnContextReducer(
        profile(), task_anchor=anchor, turn_id="active", output_tokens=500
    )
    reducer.assembled = AssembledContext(conversation_id="window")
    reducer.dispatch_generation = 2
    captured = mock_stream(monkeypatch)
    result, blocked = asyncio.run(reducer.compress(messages))
    assert not blocked
    assert captured == []
    assert messages == original
    checkpoint = store.load("window", scope="active")
    assert checkpoint["state"]["covered_call_ids"] == ["a", "b"]
    resumed = [{"role": "system", "content": "rules"}, *checkpoint["state"]["messages"]]
    second, report = reduce_tool_results(resumed, input_limit=reducer.blocking_limit)
    assert window.wire(second) == window.wire(result)
    assert second[1:] == result[1:]
    assert report["projected_results"] == []
    assert checkpoint["version"] == 1


def test_current_anchor_restoration_never_duplicates_or_reorders_it(monkeypatch):
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    mock_stream(monkeypatch)
    anchor = window.item(
        {"role": "user", "content": "exact current"}, "user", identity="turn:active"
    )
    initial = window.item(
        {"role": "user", "content": "current attachments"}, "attachment_manifest"
    )
    reducer = ActiveTurnContextReducer(profile(), task_anchor=anchor, output_tokens=500)
    reducer.client = object()
    reducer.initial_context = [initial]
    reducer.runtime_state = "latest pending action"
    messages = [
        {"role": "system", "content": "rules"},
        window.item({"role": "user", "content": "previous task"}, "user"),
        {"role": "assistant", "content": "previous answer"},
        initial,
        anchor,
        *batch(["last"], size=2),
    ]
    result, _ = asyncio.run(reducer.on_context_too_long(messages))
    assert result.count(anchor) == result.count(initial) == 1
    assert result.index(initial) + 1 == result.index(anchor)
    assert result.index(anchor) < next(
        i for i, m in enumerate(result) if m.get("tool_calls")
    )
    assert window.normalize_tool_pairs(result) == result
    assert result[-1]["content"] == reducer.runtime_state


def test_admission_does_not_make_read_pages_self_referential():
    messages = batch(["page"], name="read_file")
    admitted = window.admit(messages, tool_limit=400)
    assert "<tool-result-reference>" not in admitted[-1]["content"]
    assert "truncated" in admitted[-1]["content"]


def test_legacy_transcript_recovers_turn_identity_from_canonical_link(checkpoint_db):
    from app.models.chat import Conversation, ConversationMessage
    from app.models.conversation_turn import ConversationTurn
    from app.conversation.application.context_assembly_pipeline import (
        ContextAssemblyPipeline,
    )

    owner = checkpoint_db.get(Conversation, "window").user_id
    checkpoint_db.add_all(
        [
            ConversationMessage(
                conversation_id="window", seq=1, role="User", content="question"
            ),
            ConversationMessage(
                conversation_id="window",
                seq=2,
                role="Agent",
                content="answer",
                content_blocks_json=json.dumps(
                    [
                        {
                            "type": "tool_use",
                            "id": "old-call",
                            "name": "lookup",
                            "input": {},
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "old-call",
                            "content": "result",
                        },
                    ]
                ),
            ),
        ]
    )
    checkpoint_db.add(
        ConversationTurn(
            id="legacy",
            conversation_id="window",
            user_id=owner,
            mode="agent",
            message="question",
            user_message_seq=1,
            assistant_message_seq=2,
        )
    )
    checkpoint_db.commit()
    ctx = asyncio.run(
        ContextAssemblyPipeline().assemble_answer_context("window", "next")
    )
    assert ctx.window_messages[-1]["_context"]["source_turn_id"] == "legacy"
