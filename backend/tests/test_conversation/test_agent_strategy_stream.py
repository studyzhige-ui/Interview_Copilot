"""AgentLoopStrategy behaviors: streaming, tool round-trips, fallbacks.

These exercise ``app.conversation.agent_strategy`` (the L2 ReAct loop)
together with the agent_runtime primitives it drives — reasoning_content
plumbing, tool_call_id propagation, history reconstruction, graceful
fallback wiring, and structured tool metrics.
"""

import asyncio

import pytest


def _stub_empty_tool_catalog(monkeypatch):
    from types import SimpleNamespace

    async def create(*_args, **_kwargs):
        return SimpleNamespace(
            user_pk=1,
            format_prompt=lambda: "",
            get_openai_schemas=lambda: [],
        )

    monkeypatch.setattr(
        "app.conversation.agent_strategy.TurnToolCatalog.create",
        create,
    )


def test_graceful_fallback_uses_accumulated_blocks():
    """When the agent loop crashes mid-turn, the fallback message
    MUST mention which tools ran and surface any LLM-emitted reasoning
    text rather than collapsing to a content-less "请稍后重试"."""
    from app.conversation.agent_strategy import _build_graceful_fallback

    blocks = [
        {"type": "text", "text": "好的，我来帮你找 Agent 相关的工作。"},
        {"type": "tool_use", "name": "search_jobs", "id": "x", "input": {}},
        {
            "type": "tool_result",
            "tool_use_id": "x",
            "is_error": False,
            "summary": "返回 0 条结果",
            "content": "{}",
            "latency_ms": 1300,
        },
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

    from app.agent_runtime.react_agent import AgentRunState
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
        yield _FakeChunk(
            tool_call=SimpleNamespace(
                index=0,
                id="call_x",
                function=SimpleNamespace(
                    name="search_jobs", arguments='{"keywords":"AI"}'
                ),
            )
        )
        # Usage (terminator)
        yield _FakeChunk(
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=SimpleNamespace(cached_tokens=4),
                cache_creation_input_tokens=3,
            )
        )

    strategy = AgentLoopStrategy()
    budget = AgentRunState(started_at=0.0)
    tool_calls_acc: list = []
    reasoning_acc: list[str] = []

    async def drain():
        async for _ in strategy._consume_stream(
            fake_stream(),
            budget,
            tool_calls_acc,
            reasoning_acc,
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
    assert budget.prompt_tokens == 10
    assert budget.completion_tokens == 5
    assert budget.cache_read_tokens == 4
    assert budget.cache_creation_tokens == 3


def test_agent_provider_payload_partitions_stable_and_dynamic_context(monkeypatch):
    from types import SimpleNamespace

    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.events import HarnessEvent
    from app.conversation.strategy import StrategyContext, StrategyResult
    from app.services.chat.context_assembly_pipeline import AssembledContext

    schema = {
        "type": "function",
        "function": {
            "name": "real_tool",
            "description": "SCHEMA_ONLY_DESCRIPTION",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def create_catalog(*_args, **_kwargs):
        return SimpleNamespace(
            user_pk=1,
            format_prompt=lambda: "OPTIONAL_TOOL_GUIDANCE",
            get_openai_schemas=lambda: [schema],
        )

    async def persist(*_args, **_kwargs):
        return None

    profile = SimpleNamespace(
        model="test-model",
        supports_function_calling=True,
        context_window=128_000,
        max_output_tokens=4_000,
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.build_async_openai_client_for_role",
        lambda *_args, **_kwargs: (object(), profile),
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.TurnToolCatalog.create", create_catalog
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy._load_agent_task_snapshot",
        lambda *_args: None,
    )
    monkeypatch.setattr("app.conversation.agent_strategy.persist_turn_budget", persist)

    captured: dict = {}

    async def fake_loop(self, **kwargs):
        captured.update(kwargs)
        yield HarnessEvent.text("done", step=1, elapsed_ms=0)

    monkeypatch.setattr(AgentLoopStrategy, "_loop", fake_loop)

    assembled = AssembledContext(
        debrief_reference="STABLE_RECORD",
        summary="STABLE_SUMMARY",
        memory_block="DYNAMIC_MEMORY",
        attachment_manifest="DYNAMIC_ATTACHMENT",
        retrieved_context="DYNAMIC_RAG",
        recent_turns=[
            {"role": "User", "content": "earlier user"},
            {
                "role": "Agent",
                "content": "earlier answer",
                "blocks": [{"type": "text", "text": "earlier answer"}],
            },
        ],
        current_input="CURRENT_DIRECTION",
    )
    ctx = StrategyContext(
        user_id="alice",
        session_id="s1",
        turn_id="turn1",
        user_message="CURRENT_DIRECTION",
        assembled=assembled,
    )
    result = StrategyResult()

    async def drain():
        async for _ in AgentLoopStrategy().execute(ctx, result):
            pass

    asyncio.run(drain())

    messages = captured["messages"]
    system = messages[0]["content"]
    assert "STABLE_RECORD" not in system
    assert "STABLE_SUMMARY" not in system
    assert "OPTIONAL_TOOL_GUIDANCE" in system
    assert "SCHEMA_ONLY_DESCRIPTION" not in system
    assert "DYNAMIC_MEMORY" not in system
    assert "DYNAMIC_ATTACHMENT" not in system
    assert "DYNAMIC_RAG" not in system
    assert messages[1]["role"] == "user"
    assert "[Context Summary]" in messages[1]["content"]
    assert "STABLE_SUMMARY" in messages[1]["content"]
    assert [message["role"] for message in messages[2:4]] == ["user", "assistant"]

    current = messages[-1]["content"]
    assert "STABLE_RECORD" in current
    assert "DYNAMIC_MEMORY" in current
    assert "DYNAMIC_ATTACHMENT" in current
    assert "DYNAMIC_RAG" in current
    assert current.endswith("CURRENT_DIRECTION")
    assert captured["tool_schemas"] == [schema]


def test_agent_task_context_precedes_and_does_not_replace_current_user_anchor(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.events import HarnessEvent
    from app.conversation.strategy import StrategyContext, StrategyResult

    async def create_catalog(*_args, **_kwargs):
        return SimpleNamespace(
            user_pk=7,
            format_prompt=lambda: "",
            get_openai_schemas=lambda: [],
        )

    snapshot = {
        "id": "at_1",
        "turn_id": "turn1",
        "version": 2,
        "objective": "Complete the complex request",
        "completion_conditions": ["Done"],
        "phases": [
            {"id": "one", "title": "One", "status": "in_progress"},
            {"id": "two", "title": "Two", "status": "pending"},
        ],
    }
    monkeypatch.setattr(
        "app.conversation.agent_strategy.TurnToolCatalog.create", create_catalog
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy._load_agent_task_snapshot",
        lambda *_args: snapshot,
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.build_async_openai_client_for_role",
        lambda *_args, **_kwargs: (
            object(),
            SimpleNamespace(
                model="test",
                supports_function_calling=True,
                context_window=128_000,
                max_output_tokens=4_000,
            ),
        ),
    )

    async def persist(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.conversation.agent_strategy.persist_turn_budget", persist)
    captured = {}

    async def fake_loop(self, **kwargs):
        captured.update(kwargs)
        yield HarnessEvent.text("done", step=1, elapsed_ms=0)

    monkeypatch.setattr(AgentLoopStrategy, "_loop", fake_loop)
    result = StrategyResult()

    async def drain():
        async for _ in AgentLoopStrategy().execute(
            StrategyContext(
                user_id="alice",
                session_id="session1",
                turn_id="turn1",
                user_message="CURRENT USER DIRECTION",
            ),
            result,
        ):
            pass

    asyncio.run(drain())
    current = captured["messages"][-1]
    assert current["role"] == "user"
    assert "[AgentTask Plan" in current["content"]
    assert "Complete the complex request" in current["content"]
    assert current["content"].endswith("CURRENT USER DIRECTION")


def test_incomplete_agent_task_blocks_after_bounded_local_recovery(monkeypatch):
    from types import SimpleNamespace

    from app.agent_runtime.react_agent import AgentRunState
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.strategy import StrategyContext

    strategy = AgentLoopStrategy()

    async def fake_call(**_kwargs):
        return object(), 0.0

    async def fake_consume(*_args, **_kwargs):
        yield "premature completion"

    monkeypatch.setattr(strategy, "_call_llm_stream", fake_call)
    monkeypatch.setattr(strategy, "_consume_stream", fake_consume)
    monkeypatch.setattr(
        "app.conversation.engine.check_turn_completion",
        lambda *_args: (False, "agent_task_incomplete"),
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy._load_agent_task_snapshot",
        lambda *_args: {
            "id": "at_live",
            "objective": "Finish the complex request",
            "version": 2,
            "phases": [
                {"id": "one", "title": "One", "status": "in_progress"},
                {"id": "two", "title": "Two", "status": "pending"},
            ],
        },
    )

    class _Compactor:
        task_anchor = {"role": "user", "content": "complex request"}

        async def compress(self, messages):
            return messages, False

        def reset_circuit_breaker(self):
            return None

    ctx = StrategyContext(
        user_id="alice",
        session_id="session1",
        turn_id="turn1",
        user_message="complex request",
    )
    blocks = []
    events = []

    async def drain():
        async for event in strategy._loop(
            ctx=ctx,
            messages=[_Compactor.task_anchor],
            blocks=blocks,
            budget=AgentRunState(started_at=0.0),
            client=object(),
            profile=SimpleNamespace(),
            compactor=_Compactor(),
            tool_catalog=SimpleNamespace(user_pk=7),
            tool_schemas=[],
            base_task_content="complex request",
        ):
            events.append(event)

    asyncio.run(drain())
    assert ctx.extras["_terminal_outcome"] == "blocked"
    assert blocks[-1]["text"].startswith("本轮已保留部分结果")
    assert [event.type.value for event in events] == ["text"]
    assert "[AgentTask Plan" in _Compactor.task_anchor["content"]
    assert _Compactor.task_anchor["content"].endswith("complex request")


def _run_bounded_tool_failure_loop(monkeypatch, argument_payloads):
    from types import SimpleNamespace

    from app.agent_runtime.react_agent import AgentRunState
    from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
    from app.agent_runtime.tool_policy import ToolEffect
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.strategy import StrategyContext

    strategy = AgentLoopStrategy()
    sampled = 0

    async def fake_call(**_kwargs):
        return object(), 0.0

    async def fake_consume(
        _stream,
        _budget,
        tool_calls_acc,
        _reasoning_acc,
        **_kwargs,
    ):
        nonlocal sampled
        raw_args = argument_payloads[sampled % len(argument_payloads)]
        sampled += 1
        tool_calls_acc.append(
            _ToolCallAccumulator(
                id=f"call_{sampled}",
                name="permanent_failure",
                arguments=raw_args,
            )
        )
        if False:  # pragma: no cover - preserve async-generator shape
            yield ""

    monkeypatch.setattr(strategy, "_call_llm_stream", fake_call)
    monkeypatch.setattr(strategy, "_consume_stream", fake_consume)

    class _Catalog:
        user_pk = 7

        def __contains__(self, name):
            return name == "permanent_failure"

        @staticmethod
        def is_concurrency_safe(_name):
            return False

        @staticmethod
        def effect_for(_name):
            return ToolEffect.READ

        @staticmethod
        async def dispatch(_name, _args, _ctx):
            return {"error": "provider_unavailable", "retryable": False}

    class _Compactor:
        task_anchor = {"role": "user", "content": "complete the task"}

        async def compress(self, messages):
            return messages, False

        @staticmethod
        def reset_circuit_breaker():
            return None

    ctx = StrategyContext(
        user_id="alice",
        session_id="session1",
        turn_id=None,
        user_message="complete the task",
    )
    blocks = []
    events = []
    budget = AgentRunState(started_at=0.0)

    async def drain():
        async for event in strategy._loop(
            ctx=ctx,
            messages=[_Compactor.task_anchor],
            blocks=blocks,
            budget=budget,
            client=object(),
            profile=SimpleNamespace(),
            compactor=_Compactor(),
            tool_catalog=_Catalog(),
            tool_schemas=[],
            base_task_content="complete the task",
        ):
            events.append(event)

    asyncio.run(drain())
    return ctx, blocks, events, budget, sampled


def test_permanent_repeated_tool_failure_blocks_after_bounded_replan(monkeypatch):
    ctx, blocks, events, budget, sampled = _run_bounded_tool_failure_loop(
        monkeypatch,
        ['{"query":"same"}'],
    )

    assert sampled == 4
    assert ctx.extras["_terminal_outcome"] == "blocked"
    assert budget.stop_reason in {"repeated_tool_failure", "tool_no_progress"}
    assert len([block for block in blocks if block["type"] == "tool_result"]) == 4
    assert blocks[-1]["text"].startswith("工具连续返回相同失败")
    assert events[-1].type.value == "text"


def test_equivalent_argument_variants_share_failure_loop_fuse(monkeypatch):
    ctx, blocks, _events, budget, sampled = _run_bounded_tool_failure_loop(
        monkeypatch,
        [
            '{"query":"same","limit":3}',
            '{ "limit": 3, "query": "same" }',
        ],
    )

    assert sampled == 4
    assert ctx.extras["_terminal_outcome"] == "blocked"
    assert budget.local_tool_recovery_incidents == 2
    assert len([block for block in blocks if block["type"] == "tool_result"]) == 4


def test_empty_model_response_blocks_after_bounded_local_recovery(monkeypatch):
    from types import SimpleNamespace

    from app.agent_runtime.react_agent import AgentRunState
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.strategy import StrategyContext

    strategy = AgentLoopStrategy()
    calls = 0

    async def fake_call(**_kwargs):
        nonlocal calls
        calls += 1
        return object(), 0.0

    async def fake_consume(*_args, **_kwargs):
        if False:  # pragma: no cover - preserve async-generator shape
            yield ""

    monkeypatch.setattr(strategy, "_call_llm_stream", fake_call)
    monkeypatch.setattr(strategy, "_consume_stream", fake_consume)

    class _Compactor:
        task_anchor = {"role": "user", "content": "answer me"}

        async def compress(self, messages):
            return messages, False

        @staticmethod
        def reset_circuit_breaker():
            return None

    ctx = StrategyContext(
        user_id="alice",
        session_id="session1",
        turn_id=None,
        user_message="answer me",
    )
    blocks = []
    events = []
    budget = AgentRunState(started_at=0.0)

    async def drain():
        async for event in strategy._loop(
            ctx=ctx,
            messages=[_Compactor.task_anchor],
            blocks=blocks,
            budget=budget,
            client=object(),
            profile=SimpleNamespace(),
            compactor=_Compactor(),
            tool_catalog=SimpleNamespace(user_pk=7),
            tool_schemas=[],
            base_task_content="answer me",
        ):
            events.append(event)

    asyncio.run(drain())
    assert calls == 3
    assert budget.stop_reason == "empty_model_response"
    assert ctx.extras["_terminal_outcome"] == "blocked"
    assert blocks[-1]["text"].startswith("模型连续未给出")
    assert events[-1].type.value == "text"


def test_reconstruct_history_messages_rebuilds_tool_roundtrips():
    """Prior agent turns reload as real messages incl. tool_calls + tool results
    (so the agent sees its own tool history, Claude-Code style)."""
    from app.conversation.agent_strategy import _reconstruct_history_messages

    turns = [
        {
            "role": "User",
            "content": "find redis stuff",
            "blocks": [{"type": "text", "text": "find redis stuff"}],
        },
        {
            "role": "Agent",
            "content": "Here's what I found.",
            "blocks": [
                {"type": "text", "text": "Let me search."},
                {
                    "type": "tool_use",
                    "id": "tc1",
                    "name": "search_knowledge",
                    "input": {"query": "redis"},
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "tc1",
                    "content": "redis docs ...",
                },
                {"type": "text", "text": "Here's what I found."},
            ],
        },
    ]

    msgs = _reconstruct_history_messages(turns)

    assert msgs[0] == {"role": "user", "content": "find redis stuff"}
    asst = msgs[1]
    assert asst["role"] == "assistant"
    assert asst["tool_calls"][0]["id"] == "tc1"
    assert asst["tool_calls"][0]["function"]["name"] == "search_knowledge"
    assert "redis" in asst["tool_calls"][0]["function"]["arguments"]
    assert msgs[2] == {
        "role": "tool",
        "tool_call_id": "tc1",
        "content": "redis docs ...",
    }
    assert msgs[3] == {"role": "assistant", "content": "Here's what I found."}


def test_reconstruct_history_messages_legacy_text_only():
    """A turn with only a text block (legacy / L1) reconstructs without tool_calls."""
    from app.conversation.agent_strategy import _reconstruct_history_messages

    turns = [
        {
            "role": "Agent",
            "content": "plain answer",
            "blocks": [{"type": "text", "text": "plain answer"}],
        },
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
    from app.agent_runtime.react_agent import AgentRunState
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
        user_id="alice",
        session_id="s1",
        user_message="test",
        assembled=None,
    )
    budget = AgentRunState(started_at=0.0)
    budget.consume_step()
    messages: list[dict] = []
    blocks: list[dict] = []
    KNOWN_TC_ID = "call_xyz_42"
    tool_calls_acc = [
        _ToolCallAccumulator(id=KNOWN_TC_ID, name="read_resume", arguments="{}"),
    ]

    events: list = []

    async def drain():
        async for ev in strategy._execute_tools(
            ctx=ctx,
            messages=messages,
            blocks=blocks,
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
    from app.agent_runtime.react_agent import AgentRunState
    from app.conversation.agent_strategy import AgentLoopStrategy, _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    # Stub the inner tool-dispatch + persistence so _execute_tools can
    # run without touching the registry / DB / post-sampling hooks.
    # ``read_resume`` is a real registered tool, so the ``name in
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
        user_id="alice",
        session_id="s1",
        user_message="test",
        assembled=None,
    )
    budget = AgentRunState(started_at=0.0)
    budget.consume_step()  # so steps > 0 like the real loop
    messages: list[dict] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u"},
    ]
    blocks: list[dict] = []
    tool_calls_acc = [
        _ToolCallAccumulator(id="call_1", name="read_resume", arguments="{}"),
    ]

    # ── Branch 1: non-empty reasoning_content → key MUST be present ──
    async def run_with_reasoning():
        async for _ in strategy._execute_tools(
            ctx=ctx,
            messages=messages,
            blocks=blocks,
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
        _ToolCallAccumulator(id="call_2", name="read_resume", arguments="{}"),
    ]

    async def run_without_reasoning():
        async for _ in strategy._execute_tools(
            ctx=ctx,
            messages=messages2,
            blocks=[],
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


def test_concurrency_safe_tools_execute_in_parallel_and_replay_in_order(monkeypatch):
    """Independent reads overlap, but their messages/events remain deterministic."""
    from app.agent_runtime.react_agent import AgentRunState
    from app.conversation.agent_strategy import AgentLoopStrategy, _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    started: set[str] = set()
    both_started = asyncio.Event()
    active = 0
    max_active = 0

    class _Catalog:
        user_pk = 1

        def __contains__(self, name):
            return name in {"read_a", "read_b"}

        def is_concurrency_safe(self, name):
            return name in {"read_a", "read_b"}

        def effect_for(self, _name):
            from app.agent_runtime.tool_policy import ToolEffect

            return ToolEffect.READ

        async def dispatch(self, name, _args, _ctx):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.5)
            active -= 1
            return {"tool": name}

    monkeypatch.setattr(
        "app.conversation.agent_strategy.maybe_persist_result",
        lambda content, **_kwargs: content,
    )
    monkeypatch.setattr(
        "app.conversation.agent_strategy.enforce_turn_budget",
        lambda *_args, **_kwargs: None,
    )
    strategy = AgentLoopStrategy()
    messages: list[dict] = []
    blocks: list[dict] = []
    events = []

    async def drain():
        async for event in strategy._execute_tools(
            ctx=StrategyContext(
                user_id="alice",
                session_id="s1",
                user_message="compare",
            ),
            messages=messages,
            blocks=blocks,
            tool_calls_acc=[
                _ToolCallAccumulator(id="c1", name="read_a", arguments="{}"),
                _ToolCallAccumulator(id="c2", name="read_b", arguments="{}"),
            ],
            assistant_content="",
            reasoning_content="",
            budget=AgentRunState(started_at=0.0),
            tool_catalog=_Catalog(),
        ):
            events.append(event)

    asyncio.run(drain())

    assert max_active == 2
    assert [
        message["tool_call_id"] for message in messages if message["role"] == "tool"
    ] == [
        "c1",
        "c2",
    ]
    done_ids = [
        event.data["tool_call_id"]
        for event in events
        if event.type.value == "tool_done"
    ]
    assert done_ids == ["c1", "c2"]


def test_context_exhaustion_synthesizes_final_answer():
    """Context exhaustion is explicit without presenting usage as a limit."""
    import inspect

    from app.conversation.agent_strategy import AgentLoopStrategy

    src = inspect.getsource(AgentLoopStrategy.execute)
    assert "上下文窗口已耗尽" in src
    assert "Agent 无法生成最终回答" in src


def test_strategy_has_no_legacy_global_memory_gate():
    """The disabled mixed memory store must not shape the agent payload."""
    import inspect

    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.strategy import StrategyContext

    src = inspect.getsource(AgentLoopStrategy.execute)
    assert "global_memory" not in src
    assert "global_memory_on" not in StrategyContext.__dataclass_fields__


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
        def __init__(self, profile=None, user_id=None, **_kwargs):
            self.profile = profile

        async def compress(self, messages):
            return messages, False

        def reset_circuit_breaker(self):
            pass

        async def on_context_too_long(self, messages):
            return messages, False

    monkeypatch.setattr(
        "app.conversation.agent_strategy.QueryLoopCompactor",
        _StubCompactor,
    )

    _stub_empty_tool_catalog(monkeypatch)

    # Make the inner LLM-stream call blow up — this is the crash we're
    # asserting routes through the fallback.
    async def boom(*args, **kwargs):
        raise RuntimeError("simulated_llm_failure")

    monkeypatch.setattr(AgentLoopStrategy, "_call_llm_stream", boom)

    strategy = AgentLoopStrategy()
    ctx = StrategyContext(
        user_id="alice",
        session_id="s1",
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
    from app.conversation.strategy import StrategyContext, StrategyResult
    from app.core.error_messages import MSG_BALANCE

    class _StubProfile:
        model = "stub"

    monkeypatch.setattr(
        "app.conversation.agent_strategy.build_async_openai_client_for_role",
        lambda role, user_id=None: (object(), _StubProfile()),
    )

    class _StubCompactor:
        def __init__(self, profile=None, user_id=None, **_kwargs):
            self.profile = profile

        async def compress(self, messages):
            return messages, False

        def reset_circuit_breaker(self):
            pass

        async def on_context_too_long(self, messages):
            return messages, False

    monkeypatch.setattr(
        "app.conversation.agent_strategy.QueryLoopCompactor",
        _StubCompactor,
    )
    _stub_empty_tool_catalog(monkeypatch)

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
        user_id="alice",
        session_id="s1",
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

        from app.agent_runtime.react_agent import AgentRunState
        from app.conversation.agent_strategy import (
            AgentLoopStrategy,
            _ToolCallAccumulator,
        )
        from app.conversation.strategy import StrategyContext

        strategy = AgentLoopStrategy()
        ctx = StrategyContext(
            user_id="alice",
            session_id="s1",
            user_message="test",
            assembled=None,
        )
        budget = AgentRunState(started_at=0.0)
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
                ctx=ctx,
                messages=[],
                blocks=[],
                tool_calls_acc=[
                    _ToolCallAccumulator(
                        id="call_1", name="read_resume", arguments="{}"
                    ),
                ],
                assistant_content="",
                reasoning_content="",
                budget=budget,
            ):
                pass
        finally:
            target_logger.removeHandler(handler)
            target_logger.setLevel(old_level)

        metric_lines = [r for r in records if "tool_metric" in r.getMessage()]
        assert len(metric_lines) == 1
        msg = metric_lines[0].getMessage()
        assert "read_resume" in msg
        assert "latency_ms=" in msg
        assert "is_error=False" in msg
