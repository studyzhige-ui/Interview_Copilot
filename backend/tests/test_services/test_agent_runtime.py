"""Tests for the refactored Agent Harness (react_agent.py).

Covers:
  - AgentBudget: Hermes-style steps+timeout limits, correct refund semantics
  - ContextPipeline: 3-layer context management
  - tool_result_storage: 3-layer persistence
  - HarnessEvent: SSE event serialization
  - retry_utils: error classification and backoff
"""

import asyncio
import time

import pytest


# ── AgentBudget ──────────────────────────────────────────────────────────

def test_agent_budget_dataclass():
    """AgentBudget check() and refund() work correctly."""
    from app.agent_runtime.react_agent import AgentBudget

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

    budget = AgentBudget(started_at=time.perf_counter())
    for _ in range(settings.AGENT_MAX_STEPS):
        budget.consume_step()
    assert budget.check() == "max_steps_exceeded"


def test_agent_budget_no_token_limit():
    """Token usage does NOT trigger budget stop (Hermes pattern)."""
    from app.agent_runtime.react_agent import AgentBudget

    budget = AgentBudget(started_at=time.perf_counter())
    budget.prompt_tokens = 999_999
    budget.completion_tokens = 999_999
    # Token usage is tracked but never triggers a stop
    assert budget.check() is None


def test_agent_budget_refund_semantics():
    """Refund should only be used for compression-retry, not tool failure.

    This test documents the CORRECT Hermes pattern:
    - compression-retry → refund (system action, not reasoning)
    - tool failure → NO refund (LLM made a reasoning decision)
    """
    from app.agent_runtime.react_agent import AgentBudget

    budget = AgentBudget(started_at=time.perf_counter())
    budget.consume_step()
    budget.consume_step()
    assert budget.steps == 2

    # Compression-retry: refund is correct
    budget.refund_step()
    assert budget.steps == 1

    # Cannot refund below 0
    budget.refund_step()
    budget.refund_step()  # extra refund
    assert budget.steps == 0


# ── HarnessEvent ─────────────────────────────────────────────────────────

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


# ── retry_utils ──────────────────────────────────────────────────────────

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


# ── ContextPipeline ──────────────────────────────────────────────────────

def test_context_pipeline_prune():
    """ContextPipeline prunes old tool results (Layer 2)."""
    from app.agent_runtime.context_compactor import ContextPipeline

    pipeline = ContextPipeline(protect_tail=2)

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

    pruned = pipeline._prune_old_tool_results(messages)
    assert len(pruned) == len(messages)

    # First tool result (c1) should be pruned (summarized)
    tool_c1 = [m for m in pruned if m.get("tool_call_id") == "c1"][0]
    assert "[Tool result pruned" in tool_c1["content"]

    # Last two tool results should be protected
    tool_c2 = [m for m in pruned if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "B" * 500
    tool_c3 = [m for m in pruned if m.get("tool_call_id") == "c3"][0]
    assert tool_c3["content"] == "C" * 500


def test_context_pipeline_pre_llm_compact():
    """pre_llm_compact only triggers when prompt_tokens exceed threshold."""
    from app.agent_runtime.context_compactor import ContextPipeline

    pipeline = ContextPipeline(
        threshold_ratio=0.5,
        context_window=100,  # threshold = 50 tokens
        protect_tail=1,
    )

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "A" * 500},
        {"role": "tool", "tool_call_id": "c2", "content": "B" * 500},
    ]

    # Below threshold → no change
    result = pipeline.pre_llm_compact(messages, prompt_tokens=30)
    assert result[1]["content"] == "A" * 500  # unchanged

    # Above threshold → prune old
    result = pipeline.pre_llm_compact(messages, prompt_tokens=60)
    assert "[Tool result pruned" in result[1]["content"]  # c1 pruned
    assert result[2]["content"] == "B" * 500  # c2 protected


def test_context_pipeline_reactive_compact_prevents_loop():
    """Reactive compact refuses retry on second attempt (Claude Code pattern)."""
    from app.agent_runtime.context_compactor import ContextPipeline

    pipeline = ContextPipeline(protect_tail=1)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    # First attempt: should succeed
    result, should_retry = pipeline.on_context_too_long(messages)
    assert should_retry is True
    assert pipeline.has_attempted_reactive_compact is True

    # Second attempt: should refuse (prevent infinite loop)
    result, should_retry = pipeline.on_context_too_long(messages)
    assert should_retry is False


# ── tool_result_storage ──────────────────────────────────────────────────

def test_generate_preview():
    """Preview generation respects max_chars and prefers newline boundaries."""
    from app.agent_runtime.tool_result_storage import generate_preview

    # Short content → no truncation
    preview, has_more = generate_preview("hello world", max_chars=100)
    assert preview == "hello world"
    assert has_more is False

    # Long content → truncated at newline
    content = "line1\nline2\nline3\nline4\n" * 100
    preview, has_more = generate_preview(content, max_chars=50)
    assert has_more is True
    assert len(preview) <= 50


def test_resolve_threshold():
    """read_file threshold is infinity, others use default."""
    from app.agent_runtime.tool_result_storage import resolve_threshold

    assert resolve_threshold("read_file") == float("inf")
    assert resolve_threshold("web_search") == 30_000  # default


def test_maybe_persist_result_small(tmp_path, monkeypatch):
    """Small results pass through unchanged."""
    from app.agent_runtime.tool_result_storage import maybe_persist_result

    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.AGENT_PERSIST_THRESHOLD", 100)

    result = maybe_persist_result(
        content="small result",
        tool_name="web_search",
        tool_call_id="tc_001",
        session_id="sess_001",
    )
    assert result == "small result"


def test_maybe_persist_result_large(tmp_path, monkeypatch):
    """Large results are persisted to disk with preview."""
    from app.agent_runtime.tool_result_storage import (
        PERSISTED_OUTPUT_TAG,
        maybe_persist_result,
    )

    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.AGENT_PERSIST_THRESHOLD", 50)
    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.AGENT_PERSIST_PREVIEW_SIZE", 20)

    content = "X" * 200
    result = maybe_persist_result(
        content=content,
        tool_name="web_search",
        tool_call_id="tc_large",
        session_id="sess_persist",
    )

    assert PERSISTED_OUTPUT_TAG in result
    assert "tc_large" in result
    assert "200" in result  # original size mentioned

    # Verify file was actually written
    persisted_file = tmp_path / "agent-results" / "sess_persist" / "tc_large.txt"
    assert persisted_file.exists()
    assert persisted_file.read_text(encoding="utf-8") == content


def test_maybe_persist_result_read_file_never_persists(tmp_path, monkeypatch):
    """read_file results are NEVER persisted (prevents persist→read loop)."""
    from app.agent_runtime.tool_result_storage import (
        PERSISTED_OUTPUT_TAG,
        maybe_persist_result,
    )

    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.AGENT_PERSIST_THRESHOLD", 10)

    content = "Y" * 200
    result = maybe_persist_result(
        content=content,
        tool_name="read_file",
        tool_call_id="tc_rf",
        session_id="sess_rf",
    )

    # read_file output must pass through unchanged
    assert result == content
    assert PERSISTED_OUTPUT_TAG not in result


def test_enforce_turn_budget(tmp_path, monkeypatch):
    """Turn budget enforcement spills the largest results."""
    from app.agent_runtime.tool_result_storage import (
        PERSISTED_OUTPUT_TAG,
        enforce_turn_budget,
    )

    # Budget 4900, total = 100 + 5000 + 50 = 5150 → over budget
    # t2 (5000, largest) spilled → persisted block ~400 chars
    # After: 100 + ~400 + 50 ≈ 550 → well under 4900 → done
    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.AGENT_TURN_BUDGET_CHARS", 4900)
    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.AGENT_PERSIST_PREVIEW_SIZE", 20)

    tool_messages = [
        {"role": "tool", "tool_call_id": "t1", "content": "A" * 100},
        {"role": "tool", "tool_call_id": "t2", "content": "B" * 5000},  # largest, way over
        {"role": "tool", "tool_call_id": "t3", "content": "C" * 50},
    ]

    result = enforce_turn_budget(tool_messages, session_id="sess_budget")

    # t2 (5000 chars, largest) should be persisted
    assert PERSISTED_OUTPUT_TAG in result[1]["content"]
    # t1 and t3 should be unchanged
    assert result[0]["content"] == "A" * 100
    assert result[2]["content"] == "C" * 50


def test_is_persisted_content():
    """is_persisted_content correctly detects persisted output blocks."""
    from app.agent_runtime.tool_result_storage import (
        PERSISTED_OUTPUT_TAG,
        is_persisted_content,
    )

    assert is_persisted_content(f"{PERSISTED_OUTPUT_TAG}\nsome preview") is True
    assert is_persisted_content("normal tool result") is False
