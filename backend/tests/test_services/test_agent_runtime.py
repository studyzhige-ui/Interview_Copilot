"""Tests for the refactored Agent Harness (react_agent.py).

The new agent uses a streaming architecture (run_react_agent_stream)
with the batch wrapper (run_react_agent) for API compatibility.
"""

import asyncio

import pytest


def test_agent_budget_dataclass():
    """AgentBudget check() and refund() work correctly."""
    from app.agent_runtime.react_agent import AgentBudget
    import time

    budget = AgentBudget(started_at=time.perf_counter())
    assert budget.check() is None

    budget.consume_step()
    assert budget.steps == 1

    budget.consume_tool_call("web_search")
    assert budget.tool_calls == 1
    assert budget.tool_usage["web_search"] == 1

    budget.refund_step()
    assert budget.steps == 0

    budget.prompt_tokens = 100
    budget.completion_tokens = 50
    assert budget.total_tokens == 150

    info = budget.to_dict()
    assert info["steps"] == 0
    assert info["tool_calls"] == 1


def test_agent_budget_max_steps():
    """Budget check() triggers when max steps exceeded."""
    from app.agent_runtime.react_agent import AgentBudget
    from app.core.config import settings
    import time

    budget = AgentBudget(started_at=time.perf_counter())
    for _ in range(settings.AGENT_MAX_STEPS):
        budget.consume_step()
    assert budget.check() == "max_steps_exceeded"


def test_harness_event_serialization():
    """HarnessEvent serializes to JSON correctly."""
    from app.agent_runtime.harness_events import HarnessEvent

    event = HarnessEvent.tool_start("web_search", "query=test", step=1, elapsed_ms=100.0)
    d = event.to_dict()
    assert d["type"] == "tool_start"
    assert d["data"]["tool"] == "web_search"
    assert d["step"] == 1

    json_str = event.to_json()
    assert "web_search" in json_str


def test_retry_utils_classify():
    """Error classification works for common error patterns."""
    from app.agent_runtime.retry_utils import ErrorCategory, classify_api_error

    assert classify_api_error(Exception("429 rate limit exceeded")) == ErrorCategory.RETRYABLE
    assert classify_api_error(Exception("maximum context length exceeded")) == ErrorCategory.CONTEXT_TOO_LONG
    assert classify_api_error(Exception("401 invalid_api_key")) == ErrorCategory.FATAL


def test_retry_utils_jittered_backoff():
    """Jittered backoff returns reasonable values."""
    from app.agent_runtime.retry_utils import jittered_backoff

    delay = jittered_backoff(0, base=1.0, cap=30.0)
    assert 0.5 <= delay <= 1.0

    delay = jittered_backoff(3, base=1.0, cap=30.0)
    assert delay <= 30.0


def test_context_compactor_prune():
    """Context compactor prunes old tool results."""
    from app.agent_runtime.context_compactor import AgentContextCompactor

    compactor = AgentContextCompactor(protect_tail=2)

    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "A" * 500},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_url", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "B" * 500},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c3", "function": {"name": "search_knowledge", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c3", "content": "C" * 500},
    ]

    pruned = compactor.prune_old_tool_results(messages)
    assert len(pruned) == len(messages)

    # First tool result (c1) should be pruned (summarized)
    tool_c1 = [m for m in pruned if m.get("tool_call_id") == "c1"][0]
    assert "[Tool result pruned" in tool_c1["content"]

    # Last two tool results should be protected
    tool_c2 = [m for m in pruned if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "B" * 500
    tool_c3 = [m for m in pruned if m.get("tool_call_id") == "c3"][0]
    assert tool_c3["content"] == "C" * 500
