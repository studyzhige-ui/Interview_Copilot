"""End-to-end context contracts across assembly, storage and dispatch."""

import asyncio
from types import SimpleNamespace

import pytest

from app.conversation.provider_context import compose_provider_context
from app.core.context_budget import ContextCapacityError, RequestBudget, request_tokens
from app.core.model_catalog import ModelProfile
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
)


def profile(window=4000):
    return ModelProfile(
        id="test",
        provider="test",
        model="test",
        display_name="test",
        api_base="",
        api_key_env="",
        context_window=window,
        max_output_tokens=500,
    )


def test_final_envelope_counts_tools_and_drops_whole_memory():
    ctx = AssembledContext(
        current_input="继续比较方案",
        memory_block='{"evidence": "' + "fact " * 800 + '"}',
        personalization_guidance="不要改预算",
        prompt_token_limit=500,
    )
    tools = [
        {
            "type": "function",
            "function": {"name": "lookup", "description": "schema " * 100},
        }
    ]
    out = compose_provider_context(
        ctx, renderer=PromptRenderer(), system_prompt="rules", tool_schemas=tools
    )
    assert ctx.memory_block == ""
    assert any("不要改预算" in m["content"] for m in out.messages)
    assert ctx.total_tokens == request_tokens(out.with_leading_system_message(), tools)
    assert ctx.total_tokens <= 500
    assert ctx.context_report["omitted"] == ["memory_block"]
    compose_provider_context(
        ctx, renderer=PromptRenderer(), system_prompt="rules", tool_schemas=tools
    )
    assert ctx.context_report["omitted"] == ["memory_block"]


def test_output_reserve_is_not_capped_at_twenty_thousand():
    budget = RequestBudget.resolve(128000, 32000, safety=3000)
    assert budget.input_limit == 93000
    assert 0 < budget.compact_at < budget.input_limit


def test_tool_repair_happens_before_next_user_and_never_claims_success():
    from app.core.context_messages import normalize_tool_pairs

    messages = [
        {"role": "assistant", "tool_calls": [{"id": "missing"}, {"id": "found"}]},
        {"role": "tool", "tool_call_id": "found", "content": "real"},
        {"role": "user", "content": "next"},
        {"role": "tool", "tool_call_id": "orphan", "content": "untrusted"},
    ]
    result = normalize_tool_pairs(messages)
    assert result[2]["tool_call_id"] == "missing"
    assert "unknown" in result[2]["content"]
    assert result[-1] == {"role": "user", "content": "next"}
    assert len(messages) == 4


def test_context_capacity_failure_is_actionable_and_never_retried():
    from app.core.error_messages import humanize_error
    from app.agent_runtime.retry_utils import classify_api_error, ErrorCategory

    error = ContextCapacityError("上下文超限，历史已保留")
    assert humanize_error(error) == str(error)
    assert classify_api_error(error) == ErrorCategory.FATAL


def test_final_adapter_blocks_oversized_schema_before_network_dispatch():
    from app.core.model_provider_adapter import (
        ModelProviderAdapter,
        build_provider_request,
    )

    calls = []

    async def create(**kw):
        calls.append(kw)
        raise AssertionError("oversized request reached network")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    request = build_provider_request(
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "type": "function",
                "function": {"name": "huge", "description": "schema " * 5000},
            }
        ],
        max_tokens=500,
        temperature=0.2,
    )
    with pytest.raises(ContextCapacityError):
        asyncio.run(
            ModelProviderAdapter(client=client, profile=profile()).start_stream(request)
        )
    assert calls == []


def test_planner_gets_compacted_history_without_truncating_current_input(monkeypatch):
    import json
    from app.conversation import query_planner as planner

    calls = []

    async def complete(prompt, **kw):
        calls.append((prompt, kw))
        return SimpleNamespace(text=json.dumps({"needs_knowledge_retrieval": False}))

    monkeypatch.setattr(
        planner, "get_internal_llm", lambda _: SimpleNamespace(acomplete=complete)
    )
    monkeypatch.setattr(planner, "get_internal_model_profile", lambda _: profile(3000))
    current = "继续那个 Redis 方案，不改变之前的薪资约束。"
    result = asyncio.run(
        planner.plan_query(
            user_message=current,
            recent_turns=[
                {"role": "User", "content": "old " * 5000},
                {"role": "Agent", "content": "old answer"},
            ],
            conversation_summary="此前讨论的方案是 Redis 缓存；薪资底线 35k。",
        )
    )
    assert not result.planner_failed
    assert "35k" in calls[0][0]
    assert calls[0][0].endswith(current)
    assert "old answer" not in calls[0][0]
    assert calls[0][1]["max_tokens"] == 500
