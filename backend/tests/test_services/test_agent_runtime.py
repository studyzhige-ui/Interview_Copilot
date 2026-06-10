"""Tests for the agent_runtime primitives.

The agent loop itself lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`; this file
covers the lower-layer building blocks the strategy depends on.

Covers:
  - AgentBudget: Hermes-style steps+timeout limits, correct refund semantics
  - QueryLoopCompactor: unconditional microcompact + threshold LLM autocompact
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


async def _stub_autocompact(self, messages, *, keep_last=2):
    """No-op autocompact — isolates compress() tests from the LLM."""
    return messages


# ── Microcompact (unconditional, keep-last-N) ────────────────────────────


def test_microcompact_clears_old_keeps_recent():
    """Microcompact keeps the last 5 compactable results, clears the rest."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor, _CLEARED_CONTENT

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [{"role": "system", "content": "sys"}]
    # 7 compactable tool results → should keep last 5, clear first 2
    for i in range(7):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result_{i}"})

    result = pipeline._microcompact(messages)

    # First 2 cleared
    assert [m for m in result if m.get("tool_call_id") == "c0"][0]["content"] == _CLEARED_CONTENT
    assert [m for m in result if m.get("tool_call_id") == "c1"][0]["content"] == _CLEARED_CONTENT
    # Last 5 kept
    for i in range(2, 7):
        assert [m for m in result if m.get("tool_call_id") == f"c{i}"][0]["content"] == f"result_{i}"


def test_microcompact_skips_non_compactable_tools():
    """Non-compactable tools are never cleared, regardless of position."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [{"role": "system", "content": "sys"}]
    # 6 compactable + 1 non-compactable tool
    for i in range(6):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result_{i}"})
    # Insert a non-compactable tool result at the beginning (oldest)
    messages.insert(1, {"role": "assistant", "content": "", "tool_calls": [
        {"id": "nc1", "function": {"name": "some_custom_tool", "arguments": "{}"}}
    ]})
    messages.insert(2, {"role": "tool", "tool_call_id": "nc1", "content": "non-compactable result"})

    result = pipeline._microcompact(messages)

    # Non-compactable result preserved regardless
    nc = [m for m in result if m.get("tool_call_id") == "nc1"][0]
    assert nc["content"] == "non-compactable result"


def test_microcompact_skips_persisted_results():
    """Persisted (<persisted-output>) results are never cleared."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor
    from app.agent_runtime.tool_result_storage import PERSISTED_OUTPUT_TAG

    persisted = (
        f"{PERSISTED_OUTPUT_TAG}\n"
        "Full output saved to: /data/agent-results/sess/c0.txt\n"
        "</persisted-output>"
    )
    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [{"role": "system", "content": "sys"}]
    # 7 compactable results, first one is persisted
    for i in range(7):
        content = persisted if i == 0 else f"result_{i}"
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": content})

    result = pipeline._microcompact(messages)

    # Persisted result (c0) preserved
    c0 = [m for m in result if m.get("tool_call_id") == "c0"][0]
    assert PERSISTED_OUTPUT_TAG in c0["content"]


def test_microcompact_noop_when_under_keep_limit():
    """No clearing when total compactable results <= _KEEP_RECENT."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [{"role": "system", "content": "sys"}]
    for i in range(3):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result_{i}"})

    result = pipeline._microcompact(messages)

    # All kept — no change
    for i in range(3):
        assert [m for m in result if m.get("tool_call_id") == f"c{i}"][0]["content"] == f"result_{i}"


def test_microcompact_copy_on_write():
    """Microcompact does not modify the original messages list."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor, _CLEARED_CONTENT

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [{"role": "system", "content": "sys"}]
    for i in range(7):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result_{i}"})

    result = pipeline._microcompact(messages)

    # Original unchanged
    assert messages[2]["content"] == "result_0"
    # Pruned copy changed
    assert [m for m in result if m.get("tool_call_id") == "c0"][0]["content"] == _CLEARED_CONTENT


def test_microcompact_skips_already_cleared():
    """Already-cleared results don't count toward the keep limit."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor, _CLEARED_CONTENT

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [{"role": "system", "content": "sys"}]
    for i in range(8):
        content = _CLEARED_CONTENT if i < 2 else f"result_{i}"
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": content})

    result = pipeline._microcompact(messages)

    # c0, c1 were already cleared — stay cleared
    assert [m for m in result if m.get("tool_call_id") == "c0"][0]["content"] == _CLEARED_CONTENT
    # 6 live results (c2..c7), keep last 5 → clear c2 only
    assert [m for m in result if m.get("tool_call_id") == "c2"][0]["content"] == _CLEARED_CONTENT
    assert [m for m in result if m.get("tool_call_id") == "c3"][0]["content"] == "result_3"


# ── compress() integration ───────────────────────────────────────────────


def test_compress_runs_microcompact_unconditionally(monkeypatch):
    """compress() runs microcompact even when total is under threshold."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor, _CLEARED_CONTENT

    monkeypatch.setattr(QueryLoopCompactor, "autocompact", _stub_autocompact)

    messages = [{"role": "system", "content": "sys"}]
    for i in range(7):
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": "web_search", "arguments": "{}"}}
        ]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"result_{i}"})

    # Huge window → well under threshold, but microcompact still runs
    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=1_000_000, max_output_tokens=0),
    )
    result, at_blocking = asyncio.run(pipeline.compress(messages))

    assert [m for m in result if m.get("tool_call_id") == "c0"][0]["content"] == _CLEARED_CONTENT
    assert [m for m in result if m.get("tool_call_id") == "c6"][0]["content"] == "result_6"
    assert at_blocking is False


def test_compress_flags_blocking_limit(monkeypatch):
    """compress() returns at_blocking_limit=True when prompt exceeds limit."""
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
    )
    _, at_blocking = asyncio.run(pipeline.compress(messages))
    assert at_blocking is True


# ── Autocompact (LLM, threshold-gated) ───────────────────────────────────


def test_autocompact_summarizes_body_keeps_head_and_tail(monkeypatch):
    """autocompact replaces old turns with one reference-only summary."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    class _StubResponse:
        text = '{"summary": "SUMMARY_BODY"}'

    class _StubLLM:
        async def acomplete(self, prompt, response_format=None):
            return _StubResponse()

    import sys
    import app.services.memory.compaction_service  # noqa: F401
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

    assert result[0]["content"] == "SYS"
    assert result[1]["content"] == "MANIFEST"
    assert result[2]["content"] == "the task"
    assert any(
        "SUMMARY_BODY" in m["content"] and "END OF CONTEXT SUMMARY" in m["content"]
        for m in result
    )
    assert result[-2:] == messages[-2:]
    assert len(result) < len(messages)


def test_autocompact_noop_when_nothing_to_summarize():
    """autocompact returns messages unchanged when body is within keep_last."""
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


# ── Blocking-limit guard ──────────────────────────────────────────────────

def test_token_warning_blocks_at_limit():
    """is_at_blocking_limit blocks when prompt_tokens approach the context window."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=100_000, max_output_tokens=0)
    )

    assert pipeline.is_at_blocking_limit(50_000) is False
    assert pipeline.is_at_blocking_limit(96_999) is False
    assert pipeline.is_at_blocking_limit(97_000) is True
    assert pipeline.is_at_blocking_limit(100_000) is True


def test_token_warning_default_1m_window():
    """1M context window: blocking at 997K tokens."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(
        profile=_profile(context_window=1_000_000, max_output_tokens=0)
    )

    assert pipeline.is_at_blocking_limit(996_999) is False
    assert pipeline.is_at_blocking_limit(997_000) is True


# ── Reactive compact + circuit breaker ───────────────────────────────────

def test_reactive_compact_prevents_loop():
    """Reactive compact refuses retry on the second attempt."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    result, should_retry = asyncio.run(pipeline.on_context_too_long(messages))
    assert should_retry is True
    assert pipeline.has_attempted_reactive_compact is True

    result, should_retry = asyncio.run(pipeline.on_context_too_long(messages))
    assert should_retry is False


def test_circuit_breaker_blocks_after_max_failures():
    """Circuit breaker blocks after 3 consecutive compact failures."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]
    pipeline._consecutive_compact_failures = 3

    result, should_retry = asyncio.run(pipeline.on_context_too_long(messages))
    assert should_retry is False
    assert pipeline.has_attempted_reactive_compact is False


def test_circuit_breaker_increments_on_compact():
    """Each reactive compact increments the failure counter."""
    import asyncio

    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 500},
    ]

    assert pipeline._consecutive_compact_failures == 0
    asyncio.run(pipeline.on_context_too_long(messages))
    assert pipeline._consecutive_compact_failures == 1


def test_circuit_breaker_resets_on_success():
    """reset_circuit_breaker clears the failure counter."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

    pipeline = QueryLoopCompactor(profile=_profile())
    pipeline._consecutive_compact_failures = 2

    pipeline.reset_circuit_breaker()
    assert pipeline._consecutive_compact_failures == 0


def test_should_compact_absolute_threshold():
    """should_compact uses the absolute effective-window threshold (not a ratio)."""
    from app.agent_runtime.context_compactor import QueryLoopCompactor

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
