"""Tests for the agent_runtime primitives.

The agent loop itself lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`; this file
covers the lower-layer building blocks the strategy depends on.

Covers:
  - AgentBudget: Hermes-style steps+timeout limits, correct refund semantics
  - QueryLoopCompactor: cheap zero-LLM context pre-pass + reactive recovery
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


def test_budget_tracks_repeated_call_signatures():
    """consume_tool_call counts identical (tool, args) signatures for the soft nudge."""
    from app.agent_runtime.react_agent import AgentBudget

    budget = AgentBudget(started_at=time.perf_counter())
    sig = 'web_search\x00{"q": "redis"}'
    assert budget.consume_tool_call("web_search", sig) == 1
    assert budget.consume_tool_call("web_search", sig) == 2
    assert budget.consume_tool_call("web_search", sig) == 3
    # Different args → its own counter
    assert budget.consume_tool_call("web_search", 'web_search\x00{}') == 1
    # tool_usage (by name) aggregates all four calls
    assert budget.tool_usage["web_search"] == 4
    # No signature → no repeat tracking
    assert budget.consume_tool_call("read_url") == 0


def test_repeat_call_nudge_is_firmer_at_six():
    """The repeated-call nudge is a soft steer at 3 and firmer (still not a hard
    stop) at 6."""
    from app.conversation.agent_strategy import _repeat_call_nudge

    soft = _repeat_call_nudge("web_search", 3)
    firm = _repeat_call_nudge("web_search", 6)
    assert "web_search" in soft and "3 times" in soft
    assert "final answer" not in soft
    assert "final answer" in firm


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

    # Insufficient balance / quota — must be FATAL (retrying never helps),
    # detected by message phrase OR a 402 status_code attribute. Regression
    # guard: before this fix a 402 fell through to the optimistic-retryable
    # default and burned the whole backoff schedule on a hopeless call.
    assert classify_api_error(
        Exception("Error code: 402 - Insufficient account balance")
    ) == ErrorCategory.FATAL

    class _Err402(Exception):
        status_code = 402
    assert classify_api_error(_Err402("payment required")) == ErrorCategory.FATAL
    assert classify_api_error(Exception("insufficient_quota")) == ErrorCategory.FATAL


def test_retry_utils_jittered_backoff():
    """Jittered backoff returns reasonable values."""
    from app.agent_runtime.retry_utils import jittered_backoff

    delay = jittered_backoff(0, base=1.0, cap=30.0)
    assert 0.5 <= delay <= 1.0

    delay = jittered_backoff(3, base=1.0, cap=30.0)
    assert delay <= 30.0


# ── QueryLoopCompactor ────────────────────────────────────────────────────

def _profile(context_window: int = 1_000_000, max_output_tokens: int = 0):
    """Minimal ModelProfile for driving QueryLoopCompactor in tests.

    max_output_tokens defaults to 0 so the effective window equals
    context_window (blocking_limit == context_window - 3_000).
    """
    from app.core.model_registry import ModelProfile

    return ModelProfile(
        id="test",
        provider="deepseek",
        display_name="Test",
        model="test-model",
        api_base="https://example.test",
        api_key_env="TEST_API_KEY",
        context_window=context_window,
        max_output_tokens=max_output_tokens,
    )


def test_context_pipeline_prune():
    """Prunes old tool results (Pass 2: summarize) outside the token-budget tail."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    # tail_budget=280 protects the last two results (B/C*500 ≈125 tok each)
    # but not the oldest (A*500 ≈63 tok). See token costs in the module.
    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=280)

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

    # Oldest tool result (c1) summarized
    tool_c1 = [m for m in pruned if m.get("tool_call_id") == "c1"][0]
    assert "result pruned" in tool_c1["content"]

    # Last two tool results protected
    tool_c2 = [m for m in pruned if m.get("tool_call_id") == "c2"][0]
    assert tool_c2["content"] == "B" * 500
    tool_c3 = [m for m in pruned if m.get("tool_call_id") == "c3"][0]
    assert tool_c3["content"] == "C" * 500


async def _stub_autocompact(self, messages, *, keep_last=2):
    """No-op autocompact — isolates compress() tests from the LLM (the LLM
    summary path is covered by test_autocompact_*)."""
    return messages


def test_compress_runs_prepass_over_threshold(monkeypatch):
    """compress() self-measures the prompt and runs the cheap pre-pass only
    when the measured total exceeds the pre-pass threshold; the protected tail
    is never pruned. (autocompact stubbed — its LLM path is tested separately.)"""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    monkeypatch.setattr(QueryLoopCompactor, "autocompact", _stub_autocompact)

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
    # Measured total ≈ 191 tokens (A*500=63, B*500=125, plus a few small msgs).

    # Threshold (300) above the measured total → no pruning, not blocking.
    low_pressure = QueryLoopCompactor(
        profile=_profile(context_window=13_300, max_output_tokens=0),
        tail_budget_tokens=150,
    )
    result, at_blocking = asyncio.run(low_pressure.compress(messages))
    assert [m for m in result if m.get("tool_call_id") == "c1"][0]["content"] == "A" * 500
    assert at_blocking is False

    # Threshold (100) below the measured total → prune c1, protect c2; not blocking.
    high_pressure = QueryLoopCompactor(
        profile=_profile(context_window=13_100, max_output_tokens=0),
        tail_budget_tokens=150,
    )
    result, at_blocking = asyncio.run(high_pressure.compress(messages))
    assert "result pruned" in [m for m in result if m.get("tool_call_id") == "c1"][0]["content"]
    assert [m for m in result if m.get("tool_call_id") == "c2"][0]["content"] == "B" * 500
    assert at_blocking is False


def test_autocompact_summarizes_body_keeps_head_and_tail(monkeypatch):
    """autocompact replaces the old turns with one reference-only summary,
    preserving the leading system block + task query + the last keep_last msgs."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    class _StubResponse:
        text = '{"summary": "SUMMARY_BODY"}'

    class _StubLLM:
        async def acomplete(self, prompt, response_format=None):
            return _StubResponse()

    # The ``compaction_service`` singleton shadows the module of the same name
    # in the package namespace, so reach the real module via sys.modules to
    # stub the LLM that summarize_conversation() calls.
    import sys
    import app.services.memory.compaction_service  # noqa: F401  (ensure loaded)
    monkeypatch.setattr(
        sys.modules["app.services.memory.compaction_service"],
        "agent_fast_llm",
        _StubLLM(),
    )

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "system", "content": "MANIFEST"},
        {"role": "user", "content": "the task"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "x"}'}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "old result"},
        {"role": "assistant", "content": "a working step"},
        {"role": "tool", "tool_call_id": "c2", "content": "recent result"},
    ]

    result = asyncio.run(pipeline.autocompact(messages, keep_last=2))

    # Leading system block + task query preserved
    assert result[0]["content"] == "SYS"
    assert result[1]["content"] == "MANIFEST"
    assert result[2]["content"] == "the task"
    # A reference-only summary message was inserted
    assert any(
        "SUMMARY_BODY" in m["content"] and "END OF CONTEXT SUMMARY" in m["content"]
        for m in result
    )
    # Last 2 messages preserved verbatim; net shorter
    assert result[-2:] == messages[-2:]
    assert len(result) < len(messages)


def test_autocompact_noop_when_nothing_to_summarize(monkeypatch):
    """autocompact returns messages unchanged when the body is within keep_last."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = asyncio.run(pipeline.autocompact(messages, keep_last=2))
    assert result == messages


def test_compress_anti_thrash_skips_after_low_savings(monkeypatch):
    """compress() stops re-running the pre-pass once the last 2 runs each
    reclaimed <10% — the cheap wins are exhausted."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    monkeypatch.setattr(QueryLoopCompactor, "autocompact", _stub_autocompact)

    # threshold = 13_010 - 13_000 = 10 (always compact); a huge tail protects
    # every message, so pruning reclaims ~nothing and savings stay at 0.
    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=13_010, max_output_tokens=0),
        tail_budget_tokens=10_000,
    )
    messages = [
        {"role": "system", "content": "system prompt here"},
        {"role": "user", "content": "a question"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "unique result " + "X" * 300},
    ]

    asyncio.run(pipeline.compress(messages))
    asyncio.run(pipeline.compress(messages))
    assert len(pipeline._recent_savings) == 2
    assert all(s < 0.10 for s in pipeline._recent_savings)
    assert pipeline._is_thrashing() is True

    # 3rd call: anti-thrash skips the pre-pass → no new saving recorded.
    asyncio.run(pipeline.compress(messages))
    assert len(pipeline._recent_savings) == 2  # unchanged — pre-pass skipped


def test_compress_flags_blocking_limit(monkeypatch):
    """compress() returns at_blocking_limit=True when even the pruned prompt
    still exceeds the blocking limit (the degenerate 'cannot fit' case)."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    monkeypatch.setattr(QueryLoopCompactor, "autocompact", _stub_autocompact)

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "B" * 500},
    ]
    # Tiny window: blocking_limit = 3_100 - 3_000 = 100; measured total > 100.
    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=3_100, max_output_tokens=0),
        tail_budget_tokens=1,
    )
    _, at_blocking = asyncio.run(pipeline.compress(messages))
    assert at_blocking is True


def test_context_pipeline_reactive_compact_prevents_loop():
    """Reactive compact refuses retry on the second attempt (Claude Code pattern)."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    # First attempt: should succeed (autocompact no-ops on this tiny body)
    result, should_retry = asyncio.run(pipeline.on_context_too_long(messages))
    assert should_retry is True
    assert pipeline.has_attempted_reactive_compact is True

    # Second attempt: should refuse (prevent infinite loop)
    result, should_retry = asyncio.run(pipeline.on_context_too_long(messages))
    assert should_retry is False


# ── Blocking-limit guard ──────────────────────────────────────────────────

def test_token_warning_blocks_at_limit():
    """is_at_blocking_limit blocks when prompt_tokens approach the context window."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=100_000, max_output_tokens=0)
    )

    # Well below limit → no block
    assert pipeline.is_at_blocking_limit(50_000) is False

    # Just below buffer → no block
    assert pipeline.is_at_blocking_limit(96_999) is False

    # At blocking limit (context_window - 3000)
    assert pipeline.is_at_blocking_limit(97_000) is True

    # Over blocking limit
    assert pipeline.is_at_blocking_limit(100_000) is True


def test_token_warning_default_1m_window():
    """1M context window: blocking at 997K tokens."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=1_000_000, max_output_tokens=0)
    )

    assert pipeline.is_at_blocking_limit(996_999) is False
    assert pipeline.is_at_blocking_limit(997_000) is True


# ── Circuit breaker ───────────────────────────────────────────────────────

def test_circuit_breaker_blocks_after_max_failures():
    """Circuit breaker blocks after 3 consecutive compact failures."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    # Manually set failure count to max
    pipeline._consecutive_compact_failures = 3

    # Should refuse even on first attempt (circuit breaker open)
    import asyncio
    result, should_retry = asyncio.run(pipeline.on_context_too_long(messages))
    assert should_retry is False
    assert pipeline.has_attempted_reactive_compact is False  # didn't even try


def test_circuit_breaker_increments_on_compact():
    """Each reactive compact increments the failure counter."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    assert pipeline._consecutive_compact_failures == 0
    import asyncio
    asyncio.run(pipeline.on_context_too_long(messages))
    assert pipeline._consecutive_compact_failures == 1


def test_circuit_breaker_resets_on_success():
    """reset_circuit_breaker clears the failure counter."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    pipeline._consecutive_compact_failures = 2

    pipeline.reset_circuit_breaker()
    assert pipeline._consecutive_compact_failures == 0


# ── Copy-on-write ─────────────────────────────────────────────────────────

def test_prune_does_not_modify_original():
    """Pruning operations must not modify the original messages list."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=150)

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


# ── Pass 1: dedup ─────────────────────────────────────────────────────────

def test_pass1_dedup_removes_duplicates():
    """Pass 1 removes duplicate tool results, keeping the last occurrence."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())

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
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())

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


# ── Pass 3: JSON-safe argument truncation ─────────────────────────────────

def test_pass3_truncate_args():
    """Pass 3 truncates old tool_call arguments, keeping the output valid JSON."""
    import json

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=100)

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

    # Old args (c1) truncated but still valid JSON (raw-char slicing would 400 the API)
    old_args = result[1]["tool_calls"][0]["function"]["arguments"]
    assert len(old_args) < len(large_args)
    assert "...[truncated]" in json.loads(old_args)["content"]

    # Protected args (c2) unchanged
    new_args = result[3]["tool_calls"][0]["function"]["arguments"]
    assert new_args == large_args


def test_full_3pass_pipeline():
    """Full pipeline: dedup + summarize + JSON-safe truncate args."""
    import json

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=130)

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

    # c1: deduped (pass 1)
    assert "[Duplicate result removed" in result[2]["content"]

    # c2: summarized (pass 2) — read_file template still contains "result pruned"
    assert "result pruned" in result[4]["content"]

    # c3: protected (tail)
    assert result[6]["content"] == "search results"

    # c1 assistant args: JSON-safe truncated (old, outside tail)
    c1_args = json.loads(result[1]["tool_calls"][0]["function"]["arguments"])
    assert "...[truncated]" in c1_args["content"]

    # c3 assistant args: protected (short, never truncated)
    c3_args = result[5]["tool_calls"][0]["function"]["arguments"]
    assert c3_args == '{"q": "test"}'


# ── Pass 2: args-aware summaries + persisted-skip ─────────────────────────

def test_pass2_summary_uses_call_args():
    """Pass-2 summaries pull identifiers (query/url) from the call ARGS, not
    the result body — so a pruned summary still says what was asked."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=1)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": '{"query": "redis pubsub"}'}}
        ]},
        # Result body is plain text with no "query" field — the old code would
        # have summarized it as "query=?"; the rewrite reads it from the args.
        {"role": "tool", "tool_call_id": "c1", "content": "plain search output " + "X" * 500},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_url", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "Z" * 500},
    ]

    result = pipeline._prune_old_tool_results(messages)

    c1 = [m for m in result if m.get("tool_call_id") == "c1"][0]
    assert "result pruned" in c1["content"]
    assert "redis pubsub" in c1["content"]  # query came from the call args


def test_pass2_skips_persisted_results():
    """Pass 2 leaves Stage-A offloaded (<persisted-output>) results intact —
    they're recoverable and lossy-summarizing would destroy the file path."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor
    from app.agent_runtime.tool_result_storage import PERSISTED_OUTPUT_TAG

    persisted = (
        f"{PERSISTED_OUTPUT_TAG}\n"
        "This tool result was too large.\n"
        "Full output saved to: /data/agent-results/sess/c1.txt\n"
        "Use the read_file tool with the path above.\n\n"
        + "preview line\n" * 40
        + "</persisted-output>"
    )
    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=1)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": persisted},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "read_url", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "Z" * 500},
    ]

    result = pipeline._prune_old_tool_results(messages)

    c1 = [m for m in result if m.get("tool_call_id") == "c1"][0]
    # Persisted block preserved (path intact), NOT lossy-summarized.
    assert PERSISTED_OUTPUT_TAG in c1["content"]
    assert "agent-results/sess/c1.txt" in c1["content"]


# ── Base-class coverage: token-budget tail + JSON-safety ──────────────────

def test_find_tail_boundary_token_budget():
    """_find_tail_boundary protects a token-budget worth of recent messages."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    # Five tool results (~125 tok each); budget 300 protects ~the last two.
    messages = [{"role": "system", "content": "sys"}]
    for i in range(5):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "B" * 500})

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=300)
    boundary = pipeline._find_tail_boundary(messages)

    # Boundary lands on an assistant-with-tool_calls (never mid-pair)
    assert messages[boundary]["role"] == "assistant"
    assert messages[boundary].get("tool_calls")
    # The two newest tool results are protected; the oldest are prunable
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    assert tool_indices[-1] >= boundary
    assert tool_indices[-2] >= boundary
    assert tool_indices[0] < boundary


def test_align_boundary_forward_never_splits_pair():
    """_align_boundary_forward walks a tool boundary back to its assistant call."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
    ]
    # A boundary pointing at the tool result (index 2) must move back to the
    # assistant (index 1) so the call/result pair is never split.
    aligned = QueryLoopCompactor._align_boundary_forward(messages, 2)
    assert aligned == 1


def test_pass3_truncate_args_json_safe():
    """Pass 3 output parses as JSON; long strings + big arrays are collapsed."""
    import json

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=1)

    big = '{"content": "' + "X" * 1000 + '", "items": [1, 2, 3, 4, 5, 6]}'
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "write_file", "arguments": big}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "noop", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
    ]

    result = pipeline._pass3_truncate_args(messages)
    args = result[0]["tool_calls"][0]["function"]["arguments"]
    parsed = json.loads(args)  # must parse — production-critical
    assert "...[truncated]" in parsed["content"]
    assert len(parsed["items"]) <= 4  # first 3 + "...and N more items"


def test_pass3_truncate_args_invalid_json_fallback():
    """Pass 3 falls back to bounded raw truncation for non-JSON arguments."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile(), tail_budget_tokens=1)

    bad_args = "not json " + "Q" * 500
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "write_file", "arguments": bad_args}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "noop", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c2", "content": "ok"},
    ]

    result = pipeline._pass3_truncate_args(messages)
    args = result[0]["tool_calls"][0]["function"]["arguments"]
    assert args.endswith("...[truncated]")
    assert len(args) < len(bad_args)


def test_should_compact_absolute_threshold():
    """should_compact uses the absolute effective-window threshold (not a ratio)."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    # context_window=13_050, max_output=0 → threshold = 13_050 - 13_000 = 50
    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=13_050, max_output_tokens=0)
    )
    assert pipeline.should_compact(49) is False
    assert pipeline.should_compact(50) is True


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
    """read_file is never offloaded (inf); other tools use the configured threshold."""
    from app.agent_runtime.tool_result_storage import resolve_threshold
    from app.core.config import settings

    assert resolve_threshold("read_file") == float("inf")
    assert resolve_threshold("web_search") == settings.AGENT_PERSIST_THRESHOLD


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


def test_resolve_persisted_path_confined(tmp_path, monkeypatch):
    """resolve_persisted_path returns files inside the session dir, blocks others."""
    from app.agent_runtime.tool_result_storage import resolve_persisted_path

    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.APP_DATA_DIR", str(tmp_path))

    session_dir = tmp_path / "agent-results" / "sess_rp"
    session_dir.mkdir(parents=True, exist_ok=True)
    good = session_dir / "tc_1.txt"
    good.write_text("payload", encoding="utf-8")

    # Inside this session's dir → resolved path
    assert resolve_persisted_path("sess_rp", str(good)) == good.resolve()
    # Missing file → None
    assert resolve_persisted_path("sess_rp", str(session_dir / "missing.txt")) is None
    # Empty path → None
    assert resolve_persisted_path("sess_rp", "") is None

    # Another session's file → None (confinement, blocks cross-session read)
    other = tmp_path / "agent-results" / "other" / "tc_1.txt"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("nope", encoding="utf-8")
    assert resolve_persisted_path("sess_rp", str(other)) is None


def test_read_file_paginates_persisted_output(tmp_path, monkeypatch):
    """read_file reads back a persisted output by path, paging via offset/limit."""
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.file_tool import ReadFileArgs, _read_file_sync

    monkeypatch.setattr("app.agent_runtime.tool_result_storage.settings.APP_DATA_DIR", str(tmp_path))

    session_dir = tmp_path / "agent-results" / "sess_pg"
    session_dir.mkdir(parents=True, exist_ok=True)
    persisted = session_dir / "tc_big.txt"
    content = "".join(str(i % 10) for i in range(120))  # 120 chars
    persisted.write_text(content, encoding="utf-8")

    ctx = AgentToolContext(user_id="u1", session_id="sess_pg")

    page1 = _read_file_sync(ReadFileArgs(path=str(persisted), offset=0, limit=50), ctx)
    assert page1["content"] == content[:50]
    assert page1["total_chars"] == 120
    assert page1["returned_chars"] == 50
    assert page1["has_more"] is True
    assert page1["next_offset"] == 50

    # Resume from the reported next_offset
    page2 = _read_file_sync(
        ReadFileArgs(path=str(persisted), offset=page1["next_offset"], limit=50), ctx
    )
    assert page2["content"] == content[50:100]
    assert page2["next_offset"] == 100

    # Final page exhausts the file
    page3 = _read_file_sync(ReadFileArgs(path=str(persisted), offset=100, limit=50), ctx)
    assert page3["content"] == content[100:]
    assert page3["has_more"] is False
    assert page3["next_offset"] is None

    # Non-confined / missing path → error dict, never an exception
    missing = _read_file_sync(ReadFileArgs(path=str(tmp_path / "nope.txt")), ctx)
    assert "error" in missing


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
