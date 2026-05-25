"""Tests for the agent_runtime primitives.

The agent loop itself lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`; this file
covers the lower-layer building blocks the strategy depends on.

Covers:
  - AgentBudget: Hermes-style steps+timeout limits, correct refund semantics
  - AgentLoopContext: 3-layer context management
  - tool_result_storage: 3-layer persistence
  - HarnessEvent: SSE event serialization
  - retry_utils: error classification and backoff
"""

import time



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


# ── AgentLoopContext ──────────────────────────────────────────────────────

def test_context_pipeline_prune():
    """AgentLoopContext prunes old tool results (Pass 2: summarize)."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=2)

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
    assert "result pruned" in tool_c1["content"]

    # Last two tool results should be protected
    tool_c2 = [m for m in pruned if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "B" * 500
    tool_c3 = [m for m in pruned if m.get("tool_call_id") == "c3"][0]
    assert tool_c3["content"] == "C" * 500


def test_context_pipeline_pre_llm_compact():
    """pre_llm_compact only triggers when prompt_tokens exceed threshold."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(
        threshold_ratio=0.5,
        context_window=100,  # threshold = 50 tokens
        protect_tail=1,
    )

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "A" * 500},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_url", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "B" * 500},
    ]

    # Below threshold → no change
    result = pipeline.pre_llm_compact(messages, prompt_tokens=30)
    tool_c1 = [m for m in result if m.get("tool_call_id") == "c1"][0]
    assert tool_c1["content"] == "A" * 500  # unchanged

    # Above threshold → prune old
    result = pipeline.pre_llm_compact(messages, prompt_tokens=60)
    tool_c1 = [m for m in result if m.get("tool_call_id") == "c1"][0]
    assert "result pruned" in tool_c1["content"]  # c1 pruned
    tool_c2 = [m for m in result if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "B" * 500  # c2 protected


def test_context_pipeline_reactive_compact_prevents_loop():
    """Reactive compact refuses retry on second attempt (Claude Code pattern)."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)
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


# ── Improvement 1: Token Warning Guard ───────────────────────────────────

def test_token_warning_blocks_at_limit():
    """is_at_blocking_limit blocks when prompt_tokens approach context window."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(context_window=100_000)

    # Well below limit → no block
    assert pipeline.is_at_blocking_limit(50_000) is False

    # Just below buffer → no block
    assert pipeline.is_at_blocking_limit(96_999) is False

    # At blocking limit (context_window - 3000)
    assert pipeline.is_at_blocking_limit(97_000) is True

    # Over blocking limit
    assert pipeline.is_at_blocking_limit(100_000) is True


def test_token_warning_default_1m_window():
    """Default 1M context window: blocking at 997K tokens."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext()  # default 1M window

    assert pipeline.is_at_blocking_limit(996_999) is False
    assert pipeline.is_at_blocking_limit(997_000) is True


# ── Improvement 2: Circuit Breaker ───────────────────────────────────────

def test_circuit_breaker_blocks_after_max_failures():
    """Circuit breaker blocks after 3 consecutive compact failures."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    # Manually set failure count to max
    pipeline._consecutive_compact_failures = 3

    # Should refuse even on first attempt (circuit breaker open)
    result, should_retry = pipeline.on_context_too_long(messages)
    assert should_retry is False
    assert pipeline.has_attempted_reactive_compact is False  # didn't even try


def test_circuit_breaker_increments_on_compact():
    """Each reactive compact increments the failure counter."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    assert pipeline._consecutive_compact_failures == 0
    pipeline.on_context_too_long(messages)
    assert pipeline._consecutive_compact_failures == 1


def test_circuit_breaker_resets_on_success():
    """reset_circuit_breaker clears the failure counter."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext()
    pipeline._consecutive_compact_failures = 2

    pipeline.reset_circuit_breaker()
    assert pipeline._consecutive_compact_failures == 0


# ── Improvement 3: Copy-on-write ─────────────────────────────────────────

def test_prune_does_not_modify_original():
    """Pruning operations must not modify the original messages list."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)

    original_content = "A" * 500
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{" + "x" * 500 + "}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": original_content},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_url", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "B" * 500},
    ]

    # Keep references to originals
    original_messages_copy = [dict(m) for m in messages]

    pruned = pipeline._prune_old_tool_results(messages)

    # Original list should be unchanged
    assert len(messages) == len(original_messages_copy)
    assert messages[2]["content"] == original_content  # not modified
    # Pruned list should be different
    assert "result pruned" in pruned[2]["content"]


# ── Improvement 4: 3-pass Pruning ────────────────────────────────────────

def test_pass1_dedup_removes_duplicates():
    """Pass 1 removes duplicate tool results, keeping the last occurrence."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)

    # Same tool, same content → duplicate
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "file content here"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "file content here"},
    ]

    result = pipeline._pass1_dedup(messages)

    # First occurrence (c1) should be replaced
    tool_c1 = [m for m in result if m.get("tool_call_id") == "c1"][0]
    assert "[Duplicate result removed" in tool_c1["content"]

    # Last occurrence (c2) should be kept
    tool_c2 = [m for m in result if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "file content here"


def test_pass1_dedup_different_content_not_removed():
    """Pass 1 does NOT remove results with different content."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": '{"q": "redis"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "Redis result 1"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "web_search", "arguments": '{"q": "kafka"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "Kafka result 2"},
    ]

    result = pipeline._pass1_dedup(messages)

    # Different content → both kept
    tool_c1 = [m for m in result if m.get("tool_call_id") == "c1"][0]
    assert tool_c1["content"] == "Redis result 1"
    tool_c2 = [m for m in result if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "Kafka result 2"


def test_pass3_truncate_args():
    """Pass 3 truncates old assistant tool_call arguments."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)

    large_args = '{"content": "' + "X" * 1000 + '"}'
    messages = [
        {"role": "system", "content": "sys"},
        # Old assistant message with large args (should be truncated)
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "write_file", "arguments": large_args}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        # Recent assistant message (protected)
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "write_file", "arguments": large_args}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
    ]

    result = pipeline._pass3_truncate_args(messages)

    # Old args (c1) should be truncated
    old_args = result[1]["tool_calls"][0]["function"]["arguments"]
    assert len(old_args) < len(large_args)
    assert old_args.endswith("...[truncated]")

    # Protected args (c2) should be unchanged
    new_args = result[3]["tool_calls"][0]["function"]["arguments"]
    assert new_args == large_args


def test_full_3pass_pipeline():
    """Full 3-pass pipeline: dedup + summarize + truncate args."""
    from app.agent_runtime.context_compactor import AgentLoopContext

    pipeline = AgentLoopContext(protect_tail=1)

    large_args = '{"content": "' + "Y" * 1000 + '"}'
    messages = [
        {"role": "system", "content": "sys"},
        # Duplicate pair (same tool + same content)
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "read_file", "arguments": large_args}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "same content " + "Z" * 500},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_file", "arguments": large_args}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "same content " + "Z" * 500},
        # Unique result (protected tail)
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c3", "function": {"name": "web_search", "arguments": '{"q": "test"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c3", "content": "search results"},
    ]

    result = pipeline._prune_old_tool_results(messages)

    # c1: deduped (pass 1) → "[Duplicate result removed...]"
    assert "[Duplicate result removed" in result[2]["content"]

    # c2: summarized (pass 2) because it's old and large
    assert "[Tool result pruned" in result[4]["content"]

    # c3: protected (tail)
    assert result[6]["content"] == "search results"

    # c1 assistant args: truncated (pass 3, old and outside tail)
    c1_args = result[1]["tool_calls"][0]["function"]["arguments"]
    assert c1_args.endswith("...[truncated]")

    # c3 assistant args: protected
    c3_args = result[5]["tool_calls"][0]["function"]["arguments"]
    assert c3_args == '{"q": "test"}'


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
