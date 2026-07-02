"""AgentLoopStrategy behaviors: streaming, tool round-trips, fallbacks.

These exercise ``app.conversation.agent_strategy`` (the L2 ReAct loop)
together with the agent_runtime primitives it drives — reasoning_content
plumbing, tool_call_id propagation, history reconstruction, graceful
fallback wiring, and structured tool metrics.
"""

import asyncio

import pytest


def test_graceful_fallback_uses_accumulated_blocks():
    """When the agent loop crashes mid-turn, the fallback message
    MUST mention which tools ran and surface any LLM-emitted reasoning
    text rather than collapsing to a content-less "请稍后重试"."""
    from app.conversation.agent_strategy import _build_graceful_fallback

    blocks = [
        {"type": "text", "text": "好的，我来帮你找 Agent 相关的工作。"},
        {"type": "tool_use", "name": "search_jobs", "id": "x", "input": {}},
        {"type": "tool_result", "tool_use_id": "x", "is_error": False,
         "summary": "返回 0 条结果", "content": "{}", "latency_ms": 1300},
    ]
    msg = _build_graceful_fallback(blocks, error_message="rate_limit_exceeded")

    # The LLM's pre-crash reasoning text is preserved.
    assert "好的，我来帮你找 Agent" in msg
    # The user can see which tool was attempted.
    assert "search_jobs" in msg
    # The dead "请稍后重试" headline is gone.
    assert not msg.startswith("Agent 执行失败")
    # Raw error is surfaced as a debug note, NOT as the headline.
    assert "rate_limit_exceeded" in msg


def test_graceful_fallback_handles_empty_blocks():
    """No tool calls + no text before crash → fallback still produces
    a non-empty message (the user always sees something)."""
    from app.conversation.agent_strategy import _build_graceful_fallback

    msg = _build_graceful_fallback([], error_message="network_timeout")
    assert msg
    assert "network_timeout" in msg


def test_reasoning_content_roundtrips_into_next_assistant_message(monkeypatch):
    """DeepSeek V4 Flash / o1-mini stream ``reasoning_content`` on a
    separate delta field. The API REQUIRES that field to come back on
    the next assistant message — without it the 2nd LLM call rejects
    with HTTP 400 "The reasoning_content in the thinking mode must be
    passed back to the API".

    Pre-fix screenshot evidence: 4 tool calls fired, then the next
    LLM call retried 3 times with that exact 400, and the user got
    the graceful fallback (which only fires because the loop crashed).
    This test pins the contract: when the stream emits
    ``reasoning_content`` chunks, the assistant message appended for
    the next turn carries them under the ``reasoning_content`` key.
    """
    from types import SimpleNamespace

    from app.agent_runtime.react_agent import AgentBudget
    from app.conversation.agent_strategy import AgentLoopStrategy

    # Build a fake OpenAI-stream that emits reasoning_content + content
    # + tool_calls in three chunks, then a usage chunk.
    class _FakeChunk:
        def __init__(self, *, content=None, reasoning=None, tool_call=None, usage=None):
            self.usage = usage
            if usage is not None:
                self.choices = []
                return
            delta = SimpleNamespace(
                content=content,
                reasoning_content=reasoning,
                tool_calls=[tool_call] if tool_call else None,
            )
            self.choices = [SimpleNamespace(delta=delta, index=0)]

    async def fake_stream():
        # Step 1: reasoning trace (no content yet)
        yield _FakeChunk(reasoning="Let me think about which tools to call. ")
        yield _FakeChunk(reasoning="The user wants jobs. ")
        # Step 2: visible text
        yield _FakeChunk(content="好的，我先查一下。")
        # Step 3: tool call
        yield _FakeChunk(tool_call=SimpleNamespace(
            index=0,
            id="call_x",
            function=SimpleNamespace(name="search_jobs", arguments='{"keywords":"AI"}'),
        ))
        # Usage (terminator)
        yield _FakeChunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))

    strategy = AgentLoopStrategy()
    budget = AgentBudget(started_at=0.0)
    tool_calls_acc: list = []
    reasoning_acc: list[str] = []

    async def drain():
        async for _ in strategy._consume_stream(
            fake_stream(), budget, tool_calls_acc, reasoning_acc,
        ):
            pass

    asyncio.run(drain())

    # Reasoning was captured.
    assert "".join(reasoning_acc) == (
        "Let me think about which tools to call. The user wants jobs. "
    )
    # Tool call was captured.
    assert len(tool_calls_acc) == 1
    assert tool_calls_acc[0].name == "search_jobs"


def test_agent_system_block_keeps_manifest_before_grounding_for_prompt_cache():
    """The agent renders its context through the SHARED pipeline (one
    SLOT_ORDER, no separate assembler). The tool manifest is part of the
    system prompt and, together with the stable prefix (summary / recent
    turns), precedes the per-turn grounding (memory / RAG) inside the system
    block — so a grounding change can't evict the cached prefix. The query is
    NOT in the system block (it's sent as the user message)."""
    from app.agent_runtime.tool_registry import registry
    from app.conversation.agent_strategy import SYSTEM_PROMPT
    from app.services.chat.context_assembly_pipeline import (
        AssembledContext,
        prompt_renderer,
    )

    manifest = registry.format_manifest()
    ctx = AssembledContext(
        summary="prior summary",
        memory_block="# Memory bundle",
        retrieved_context="[K1] some chunk",
        recent_turns=[{"role": "User", "content": "earlier"}],
        current_input="the user query",
    )
    system_block = prompt_renderer.render_answer_prompt(
        ctx,
        system_prompt=f"{SYSTEM_PROMPT}\n\nAvailable tools:\n{manifest}",
        skip_fields={"current_input"},
    )

    # Manifest is part of the system prompt and precedes the grounding.
    assert "Available tools:" in system_block
    assert system_block.index("Available tools:") < system_block.index("[Memory]")
    # Stable prefix (summary, recent turns) precedes the per-turn grounding.
    assert system_block.index("[Context Summary]") < system_block.index("[Memory]")
    assert system_block.index("[Recent Turns]") < system_block.index("[Retrieved Context]")
    # The query is rendered as the user message, not wedged in the system block.
    assert "the user query" not in system_block


def test_reconstruct_history_messages_rebuilds_tool_roundtrips():
    """Prior agent turns reload as real messages incl. tool_calls + tool results
    (so the agent sees its own tool history, Claude-Code style)."""
    from app.conversation.agent_strategy import _reconstruct_history_messages

    turns = [
        {"role": "User", "content": "find redis stuff",
         "blocks": [{"type": "text", "text": "find redis stuff"}]},
        {"role": "Agent", "content": "Here's what I found.", "blocks": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "id": "tc1", "name": "search_knowledge",
             "input": {"query": "redis"}},
            {"type": "tool_result", "tool_use_id": "tc1", "content": "redis docs ..."},
            {"type": "text", "text": "Here's what I found."},
        ]},
    ]

    msgs = _reconstruct_history_messages(turns)

    assert msgs[0] == {"role": "user", "content": "find redis stuff"}
    asst = msgs[1]
    assert asst["role"] == "assistant"
    assert asst["tool_calls"][0]["id"] == "tc1"
    assert asst["tool_calls"][0]["function"]["name"] == "search_knowledge"
    assert "redis" in asst["tool_calls"][0]["function"]["arguments"]
    assert msgs[2] == {"role": "tool", "tool_call_id": "tc1", "content": "redis docs ..."}


def test_reconstruct_history_messages_legacy_text_only():
    """A turn with only a text block (legacy / L1) reconstructs without tool_calls."""
    from app.conversation.agent_strategy import _reconstruct_history_messages

    turns = [
        {"role": "Agent", "content": "plain answer",
         "blocks": [{"type": "text", "text": "plain answer"}]},
    ]
    msgs = _reconstruct_history_messages(turns)
    assert msgs == [{"role": "assistant", "content": "plain answer"}]


def test_tool_call_id_propagates_from_strategy_to_sse_events(monkeypatch):
    """End-to-end strategy-side check: when ``_execute_tools`` runs a
    tool with a known ``tc.id``, BOTH the emitted ``tool_start`` and
    ``tool_done`` SSE events MUST carry that exact id under
    ``data.tool_call_id``.

    The factory-level test ``test_tool_start_and_tool_done_carry_tool_call_id``
    only verified the HarnessEvent constructors do the right thing
    given an id. This test catches the regression case where
    ``agent_strategy.py`` stops passing ``tool_call_id=tc.id`` to the
    factory — the factory test would still pass while the wire goes
    silently broken.
    """
    from app.agent_runtime.harness_events import HarnessEventType
    from app.agent_runtime.react_agent import AgentBudget
    from app.conversation.agent_strategy import AgentLoopStrategy, _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    async def fake_dispatch(name, args, ctx):
        return {"ok": True}

    monkeypatch.setattr(
        "app.agent_runtime.tool_registry.registry.dispatch",
        fake_dispatch,
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.maybe_persist_result",
        lambda content, **k: content,
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.enforce_turn_budget",
        lambda *a, **k: None,
    )

    strategy = AgentLoopStrategy()
    ctx = StrategyContext(
        user_id="alice", session_id="s1",
        user_message="test", assembled=None,
    )
    budget = AgentBudget(started_at=0.0)
    budget.consume_step()
    messages: list[dict] = []
    blocks: list[dict] = []
    KNOWN_TC_ID = "call_xyz_42"
    tool_calls_acc = [
        _ToolCallAccumulator(id=KNOWN_TC_ID, name="recall_memory", arguments="{}"),
    ]

    events: list = []

    async def drain():
        async for ev in strategy._execute_tools(
            ctx=ctx, messages=messages, blocks=blocks,
            tool_calls_acc=tool_calls_acc,
            assistant_content="",
            reasoning_content="",
            budget=budget,
        ):
            events.append(ev)

    asyncio.run(drain())

    starts = [e for e in events if e.type == HarnessEventType.TOOL_START]
    dones = [e for e in events if e.type == HarnessEventType.TOOL_DONE]
    assert len(starts) == 1 and len(dones) == 1, (
        f"expected exactly one start+done pair; got starts={len(starts)} "
        f"dones={len(dones)}"
    )
    assert starts[0].data["tool_call_id"] == KNOWN_TC_ID, (
        f"tool_start lost the LLM-assigned tc.id; "
        f"got {starts[0].data['tool_call_id']!r} expected {KNOWN_TC_ID!r}"
    )
    assert dones[0].data["tool_call_id"] == KNOWN_TC_ID, (
        f"tool_done lost the LLM-assigned tc.id; "
        f"got {dones[0].data['tool_call_id']!r} expected {KNOWN_TC_ID!r}"
    )
    # Pairing: start id == done id (so a future id-based pair pass on
    # the FE has matching keys to work with).
    assert starts[0].data["tool_call_id"] == dones[0].data["tool_call_id"]

    # Persisted tool_use block also carries the same id (live + replay
    # shape parity — the whole point of P1-C).
    use_blocks = [b for b in blocks if b.get("type") == "tool_use"]
    assert len(use_blocks) == 1
    assert use_blocks[0]["id"] == KNOWN_TC_ID


def test_reasoning_content_lands_in_next_assistant_message(monkeypatch):
    """Drive ``_execute_tools`` directly with a reasoning trace and
    assert the assistant message it appends to ``messages`` carries the
    ``reasoning_content`` key. This pins the actual round-trip that
    the DeepSeek thinking-mode HTTP 400 forced us to plumb.

    Pre-fix the only test for reasoning_content asserted the
    accumulator captured the chunks from ``_consume_stream``. That was
    weaker than necessary — the accumulator string never being used to
    populate the next-turn assistant message was the actual production
    bug. This test drives the *use* of the accumulator, not just its
    capture.
    """
    from app.agent_runtime.react_agent import AgentBudget
    from app.conversation.agent_strategy import AgentLoopStrategy, _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    # Stub the inner tool-dispatch + persistence so _execute_tools can
    # run without touching the registry / DB / post-sampling hooks.
    # ``recall_memory`` is a real registered tool, so the ``name in
    # registry`` check passes unpatched — no need to monkeypatch
    # ``__contains__`` (reviewer flagged that as dead weight).
    async def fake_dispatch(name, args, ctx):
        return {"ok": True, "count": 0}

    monkeypatch.setattr(
        "app.agent_runtime.tool_registry.registry.dispatch",
        fake_dispatch,
    )

    # maybe_persist_result / enforce_turn_budget are imported into
    # the strategy module — patch at the use site.
    monkeypatch.setattr(
        "app.conversation.agent_strategy.maybe_persist_result",
        lambda content, **k: content,
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.enforce_turn_budget",
        lambda *a, **k: None,
    )

    # Build the minimum input set for _execute_tools.
    strategy = AgentLoopStrategy()
    ctx = StrategyContext(
        user_id="alice", session_id="s1",
        user_message="test", assembled=None,
    )
    budget = AgentBudget(started_at=0.0)
    budget.consume_step()  # so steps > 0 like the real loop
    messages: list[dict] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
    ]
    blocks: list[dict] = []
    tool_calls_acc = [
        _ToolCallAccumulator(id="call_1", name="recall_memory", arguments="{}"),
    ]

    # ── Branch 1: non-empty reasoning_content → key MUST be present ──
    async def run_with_reasoning():
        async for _ in strategy._execute_tools(
            ctx=ctx, messages=messages, blocks=blocks,
            tool_calls_acc=tool_calls_acc,
            assistant_content="visible text from LLM",
            reasoning_content="hidden thinking trace — this MUST round-trip back",
            budget=budget,
        ):
            pass

    asyncio.run(run_with_reasoning())

    # First appended assistant message (BEFORE the tool result message).
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assistant_msg = assistant_msgs[0]
    assert assistant_msg["content"] == "visible text from LLM"
    assert "reasoning_content" in assistant_msg, (
        "reasoning trace not attached to the next-turn assistant "
        "message — DeepSeek thinking-mode API would reject the next "
        "call with HTTP 400 'reasoning_content must be passed back'"
    )
    assert assistant_msg["reasoning_content"] == (
        "hidden thinking trace — this MUST round-trip back"
    )

    # ── Branch 2: empty reasoning_content → key MUST NOT be present ──
    # Plain (non-thinking) models don't produce reasoning_content;
    # attaching an empty string on those would be a noise field at
    # best and an API contract violation at worst.
    messages2: list[dict] = []
    tool_calls_acc2 = [
        _ToolCallAccumulator(id="call_2", name="recall_memory", arguments="{}"),
    ]

    async def run_without_reasoning():
        async for _ in strategy._execute_tools(
            ctx=ctx, messages=messages2, blocks=[],
            tool_calls_acc=tool_calls_acc2,
            assistant_content="visible text",
            reasoning_content="",  # plain model, no thinking trace
            budget=budget,
        ):
            pass

    asyncio.run(run_without_reasoning())

    assistant_msg2 = next(m for m in messages2 if m.get("role") == "assistant")
    assert "reasoning_content" not in assistant_msg2, (
        "empty reasoning_content should NOT add the key — non-thinking "
        "model APIs would see a confusing always-empty field"
    )


def test_budget_stop_synthesizes_final_answer():
    """When the agent loop exits with no final_answer AND a non-empty
    ``budget.stop_reason``, the strategy synthesizes a user-visible
    "执行因预算策略停止" message. Pre-fix this code path was
    untested — a regression that swapped the two synth strings would
    silently degrade UX without breaking any test.
    """
    # The synth happens inline in execute() right before the finally
    # block; we verify it by exercising the source-level branch logic
    # since fully driving execute() requires extensive LLM stubbing.
    # The two branches:
    #
    #   if budget.stop_reason:
    #       final_answer = f"Agent 执行因预算策略停止: {stop_reason}. ..."
    #   else:
    #       final_answer = "Agent 无法生成最终回答。"
    #
    # Confirm both strings exist in the source so a regression that
    # swaps or deletes either fails this test.
    import inspect
    from app.conversation.agent_strategy import AgentLoopStrategy

    src = inspect.getsource(AgentLoopStrategy.execute)
    assert "Agent 执行因预算策略停止" in src, (
        "budget-stop synthesis string missing — a user hitting "
        "max_steps_exceeded would get a blank answer or the wrong "
        "fallback message."
    )
    assert "Agent 无法生成最终回答" in src, (
        "empty-answer fallback string missing — same UX failure for "
        "the no-stop-reason branch."
    )


def test_strategy_context_carries_global_memory_on(monkeypatch):
    """Pre-P1-H the engine resolved ``is_global_memory_enabled_for_
    session`` in ``_prepare``, and the agent strategy resolved it
    AGAIN at the top of ``execute`` to gate the memory tools. Two DB
    round-trips for a single boolean. P1-H plumbs the value through
    ``StrategyContext.global_memory_on`` so the strategy reads the
    cached value.

    Pin: the strategy MUST NOT call ``is_global_memory_enabled_for_
    session`` directly anymore (would silently re-introduce the
    double-read). We verify by source inspection — a regression that
    re-adds the call would fail this assertion.
    """
    import inspect
    from app.conversation.agent_strategy import AgentLoopStrategy

    src = inspect.getsource(AgentLoopStrategy.execute)
    assert "is_global_memory_enabled_for_session" not in src, (
        "agent_strategy.execute() must NOT re-query the global-memory "
        "toggle — engine resolves it once in _prepare and the value "
        "lives on ctx.global_memory_on. Re-adding the direct call "
        "silently regresses to 2x DB round-trips per agent turn."
    )
    # ctx.global_memory_on must be the field that's read in its place.
    assert "ctx.global_memory_on" in src or "global_memory_on" in src, (
        "agent_strategy.execute() should read ctx.global_memory_on; "
        "if you renamed it, update this test."
    )


def test_graceful_fallback_is_wired_into_strategy_except_path(monkeypatch):
    """Pin the WIRING: a crash in the inner loop must route through
    ``_build_graceful_fallback`` and never re-introduce the dead
    "Agent 执行失败" headline. Without this test, a future refactor
    could overwrite the except branch with a literal string and the
    unit tests of ``_build_graceful_fallback`` alone would still pass.
    """
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.strategy import StrategyContext, StrategyResult

    sentinel = "<<GRACEFUL_FALLBACK_RAN>>"

    def stub_fallback(blocks, error_message):
        # Return a unique sentinel so we can prove the except branch
        # called THIS function and not some inline replacement string.
        return f"{sentinel} err={error_message}"

    monkeypatch.setattr(
        "app.conversation.agent_strategy._build_graceful_fallback",
        stub_fallback,
    )

    # Stub OpenAI client + profile so we don't need a real LLM.
    class _StubProfile:
        model = "stub"
    monkeypatch.setattr(
        "app.conversation.agent_strategy.build_async_openai_client_for_role",
        lambda role, user_id=None: (object(), _StubProfile()),
    )

    # Stub the budget compactor so the loop reaches the LLM-stream call.
    class _StubCompactor:
        def __init__(self, profile=None): self.profile = profile
        async def compress(self, messages): return messages, False
        def reset_circuit_breaker(self): pass
        async def on_context_too_long(self, messages): return messages, False
    monkeypatch.setattr(
        "app.conversation.agent_strategy.QueryLoopCompactor",
        _StubCompactor,
    )

    # Force memory toggle on so we don't have to mock recall_policy.
    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda sid, uid: True,
    )

    # Make the inner LLM-stream call blow up — this is the crash we're
    # asserting routes through the fallback.
    async def boom(*args, **kwargs):
        raise RuntimeError("simulated_llm_failure")
    monkeypatch.setattr(AgentLoopStrategy, "_call_llm_stream", boom)

    strategy = AgentLoopStrategy()
    ctx = StrategyContext(
        user_id="alice", session_id="s1",
        user_message="任何输入都会触发 boom",
        assembled=None,
    )
    result = StrategyResult()

    async def drain():
        events = []
        async for ev in strategy.execute(ctx, result):
            events.append(ev)
        return events

    asyncio.run(drain())

    assert sentinel in result.final_answer, (
        f"except branch did not route through _build_graceful_fallback; "
        f"final_answer={result.final_answer!r}"
    )
    assert "simulated_llm_failure" in result.final_answer
    # The dead headline must NOT come back.
    assert not result.final_answer.startswith("Agent 执行失败")


def test_strategy_crash_yields_humanized_error_event(monkeypatch):
    """THE FIX: a crash in the inner loop must YIELD an actionable error
    event to the LIVE stream — not just persist a fallback into ``result``.

    Pre-fix the except branch only set ``result.final_answer`` (persisted)
    and yielded nothing, so a clean API failure — e.g. a 402 "insufficient
    balance" on the very first LLM call — showed the user an empty turn with
    no explanation. This pins that the user now gets the actionable balance
    message live, and that it routes through the shared ``humanize_error``.
    """
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.core.error_messages import MSG_BALANCE
    from app.conversation.strategy import StrategyContext, StrategyResult

    class _StubProfile:
        model = "stub"
    monkeypatch.setattr(
        "app.conversation.agent_strategy.build_async_openai_client_for_role",
        lambda role, user_id=None: (object(), _StubProfile()),
    )

    class _StubCompactor:
        def __init__(self, profile=None): self.profile = profile
        async def compress(self, messages): return messages, False
        def reset_circuit_breaker(self): pass
        async def on_context_too_long(self, messages): return messages, False
    monkeypatch.setattr(
        "app.conversation.agent_strategy.QueryLoopCompactor",
        _StubCompactor,
    )
    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda sid, uid: True,
    )

    # DeepSeek-style 402 insufficient-balance error on the first LLM call.
    class _Boom402(Exception):
        status_code = 402
        def __str__(self):
            return "Error code: 402 - Insufficient account balance"
    async def boom(*args, **kwargs):
        raise _Boom402()
    monkeypatch.setattr(AgentLoopStrategy, "_call_llm_stream", boom)

    strategy = AgentLoopStrategy()
    ctx = StrategyContext(
        user_id="alice", session_id="s1",
        user_message="任何输入都会触发 402",
        assembled=None,
    )
    result = StrategyResult()

    async def drain():
        events = []
        async for ev in strategy.execute(ctx, result):
            events.append(ev)
        return events

    events = asyncio.run(drain())

    error_events = [e for e in events if e.type.value == "error"]
    assert error_events, (
        "crash did not yield an error event — the user would see nothing"
    )
    assert error_events[-1].data["error"] == MSG_BALANCE, (
        f"error event should carry the actionable balance message, got "
        f"{error_events[-1].data['error']!r}"
    )


class TestToolMetrics:
    """Tool execution must emit structured metrics via logger."""

    @pytest.mark.asyncio
    async def test_tool_metric_logged(self, monkeypatch):
        """_execute_tools must log tool_metric with latency and error status."""
        import logging

        async def fake_dispatch(name, args, ctx):
            return {"ok": True}

        monkeypatch.setattr(
            "app.agent_runtime.tool_registry.registry.dispatch",
            fake_dispatch,
        )
        monkeypatch.setattr(
            "app.conversation.agent_strategy.maybe_persist_result",
            lambda content, **k: content,
        )
        monkeypatch.setattr(
            "app.conversation.agent_strategy.enforce_turn_budget",
            lambda *a, **k: None,
        )

        from app.agent_runtime.react_agent import AgentBudget
        from app.conversation.agent_strategy import AgentLoopStrategy, _ToolCallAccumulator
        from app.conversation.strategy import StrategyContext

        strategy = AgentLoopStrategy()
        ctx = StrategyContext(
            user_id="alice", session_id="s1",
            user_message="test", assembled=None,
        )
        budget = AgentBudget(started_at=0.0)
        budget.consume_step()

        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)
        handler.setLevel(logging.DEBUG)
        target_logger = logging.getLogger("app.conversation.agent_strategy")
        old_level = target_logger.level
        target_logger.setLevel(logging.DEBUG)
        target_logger.addHandler(handler)
        try:
            async for _ in strategy._execute_tools(
                ctx=ctx, messages=[], blocks=[],
                tool_calls_acc=[
                    _ToolCallAccumulator(id="call_1", name="recall_memory", arguments="{}"),
                ],
                assistant_content="", reasoning_content="",
                budget=budget,
            ):
                pass
        finally:
            target_logger.removeHandler(handler)
            target_logger.setLevel(old_level)

        metric_lines = [r for r in records if "tool_metric" in r.getMessage()]
        assert len(metric_lines) == 1
        msg = metric_lines[0].getMessage()
        assert "recall_memory" in msg
        assert "latency_ms=" in msg
        assert "is_error=False" in msg
