"""Tests for the agent_runtime primitives.

The agent loop itself lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`; this file
covers the lower-layer building blocks the strategy depends on.

Covers:
  - AgentRunState: usage telemetry, repeat detection, and refund semantics
  - ActiveTurnContextReducer: pressure-only durable ToolResult references
  - HarnessEvent: SSE event serialization
  - retry_utils: error classification and backoff
"""

import time

# ── AgentRunState ────────────────────────────────────────────────────────


def test_agent_run_state_tracks_usage():
    from app.agent_runtime.react_agent import AgentRunState

    budget = AgentRunState(started_at=time.perf_counter())

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


def test_agent_budget_refund_semantics():
    """Refund should only be used for compression-retry, not tool failure.

    This test documents the CORRECT Hermes pattern:
    - compression-retry → refund (system action, not reasoning)
    - tool failure → NO refund (LLM made a reasoning decision)
    """
    from app.agent_runtime.react_agent import AgentRunState

    budget = AgentRunState(started_at=time.perf_counter())
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
    from app.agent_runtime.react_agent import AgentRunState

    budget = AgentRunState(started_at=time.perf_counter())
    sig = 'web_search\x00{"q": "redis"}'
    assert budget.consume_tool_call("web_search", sig) == 1
    assert budget.consume_tool_call("web_search", sig) == 2
    assert budget.consume_tool_call("web_search", sig) == 3
    # Different args → its own counter
    assert budget.consume_tool_call("web_search", "web_search\x00{}") == 1
    # tool_usage (by name) aggregates all four calls
    assert budget.tool_usage["web_search"] == 4
    # No signature → no repeat tracking
    assert budget.consume_tool_call("read_url") == 0


def test_repeat_call_nudge_is_firmer_at_six():
    """The repeated-call nudge is a soft steer at 3 and firmer (still not a hard
    stop) at 6."""
    from app.conversation.tool_batch import _repeat_call_nudge

    soft = _repeat_call_nudge("web_search", 3)
    firm = _repeat_call_nudge("web_search", 6)
    assert "web_search" in soft and "3 times" in soft
    assert "final answer" not in soft
    assert "final answer" in firm


def test_budget_requests_replan_after_repeated_failed_outcome():
    from app.agent_runtime.react_agent import AgentRunState

    budget = AgentRunState(started_at=time.perf_counter())
    assert (
        budget.observe_tool_result("fetch", "fetch\x00{}", "same error", is_error=True)
        is None
    )
    assert (
        budget.observe_tool_result("fetch", "fetch\x00{}", "same error", is_error=True)
        is None
    )
    incident = budget.observe_tool_result(
        "fetch", "fetch\x00{}", "same error", is_error=True
    )
    assert incident and "replan" in incident


def test_budget_resets_failure_streak_on_progress():
    from app.agent_runtime.react_agent import AgentRunState

    budget = AgentRunState(started_at=time.perf_counter())
    budget.observe_tool_result("fetch", "fetch\x00{}", "error", is_error=True)
    budget.observe_tool_result("fetch", "fetch\x00{}", "success", is_error=False)
    assert budget.failed_outcome_streak == 0


def test_local_tool_recovery_incidents_reset_after_genuine_progress():
    from app.agent_runtime.react_agent import AgentRunState

    budget = AgentRunState(started_at=time.perf_counter())
    for _ in range(3):
        budget.observe_tool_result("fetch", "fetch\x00{}", "same error", is_error=True)
    assert budget.local_tool_recovery_incidents == 1

    budget.observe_tool_result(
        "fetch", "fetch\x00{}", "new successful value", is_error=False
    )
    assert budget.local_tool_recovery_incidents == 0
    assert budget.local_tool_recovery_exhausted_reason is None


# ── HarnessEvent ─────────────────────────────────────────────────────────


def test_harness_event_serialization():
    """HarnessEvent serializes to JSON correctly."""
    from app.conversation.events import HarnessEvent

    event = HarnessEvent.tool_start(
        "web_search", "query=test", step=1, elapsed_ms=100.0
    )
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

    assert (
        classify_api_error(Exception("429 rate limit exceeded"))
        == ErrorCategory.RETRYABLE
    )
    assert (
        classify_api_error(Exception("maximum context length exceeded"))
        == ErrorCategory.CONTEXT_TOO_LONG
    )
    assert classify_api_error(Exception("401 invalid_api_key")) == ErrorCategory.FATAL

    # Insufficient balance / quota — must be FATAL (retrying never helps),
    # detected by message phrase OR a 402 status_code attribute. Regression
    # guard: before this fix a 402 fell through to the optimistic-retryable
    # default and burned the whole backoff schedule on a hopeless call.
    assert (
        classify_api_error(Exception("Error code: 402 - Insufficient account balance"))
        == ErrorCategory.FATAL
    )

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


# ── ActiveTurnContextReducer ──────────────────────────────────────────────


def _profile(context_window: int = 1_000_000, max_output_tokens: int = 0):
    """Minimal ModelProfile for driving the active-Turn reducer in tests.

    max_output_tokens defaults to 0 so the effective window equals
    context_window (blocking_limit == context_window - output reserve - safety margin).
    """
    from app.core.model_catalog import ModelProfile

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


def _tool_messages(*, size: int = 2_000, count: int = 3):
    messages = [{"role": "system", "content": "sys"}]
    for index in range(count):
        call_id = f"call-{index}"
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "function": {
                                "name": "web_search",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": "x" * size,
                },
            ]
        )
    return messages


def test_reducer_preserves_tool_results_below_pressure_threshold():
    import asyncio

    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    messages = _tool_messages(size=100, count=3)
    pipeline = ActiveTurnContextReducer(profile=_profile(context_window=1_000_000))
    result, at_blocking = asyncio.run(pipeline.compress(messages))

    from app.conversation.context_window import wire

    assert wire(result) == messages
    assert at_blocking is False


def test_request_measurement_counts_tools_once_and_uses_provider_delta():
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    schema = {
        "type": "function",
        "function": {
            "name": "large_tool",
            "description": "x" * 1_000,
            "parameters": {"type": "object", "properties": {}},
        },
    }
    without_tools = ActiveTurnContextReducer(profile=_profile())
    with_tools = ActiveTurnContextReducer(profile=_profile(), tool_schemas=[schema])

    assert with_tools._measure_tokens(messages) > without_tools._measure_tokens(
        messages
    )

    with_tools.observe_provider_prompt_tokens(123, messages)
    assert with_tools._measure_tokens(messages) == 123
    appended = [*messages, {"role": "assistant", "content": "new delta " * 100}]
    assert with_tools._measure_tokens(appended) > 123


# ── Blocking-limit guard ──────────────────────────────────────────────────


def test_token_warning_blocks_at_limit():
    """is_at_blocking_limit blocks when prompt_tokens approach the context window."""
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    pipeline = ActiveTurnContextReducer(
        profile=_profile(context_window=100_000, max_output_tokens=0)
    )

    assert pipeline.is_at_blocking_limit(50_000) is False
    assert pipeline.is_at_blocking_limit(98_974) is False
    assert pipeline.is_at_blocking_limit(98_975) is True
    assert pipeline.is_at_blocking_limit(100_000) is True


def test_token_warning_default_1m_window():
    """The default safety margin applies to large windows too."""
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    pipeline = ActiveTurnContextReducer(
        profile=_profile(context_window=1_000_000, max_output_tokens=0)
    )

    assert pipeline.is_at_blocking_limit(998_974) is False
    assert pipeline.is_at_blocking_limit(998_975) is True


# ── Reactive reduction ───────────────────────────────────────────────────


def test_should_compact_absolute_threshold():
    """Compaction starts before the blocking threshold at every window size."""
    from app.agent_runtime.context_compactor import ActiveTurnContextReducer

    pipeline = ActiveTurnContextReducer(
        profile=_profile(context_window=13_050, max_output_tokens=0)
    )
    assert pipeline.should_compact(pipeline.cheap_prepass_threshold - 1) is False
    assert pipeline.should_compact(pipeline.cheap_prepass_threshold) is True
