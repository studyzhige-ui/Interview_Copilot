"""Tool batch identity, policy barriers, concurrency and replay contracts."""

import asyncio

import pytest
from app.conversation.tool_batch import execute_tool_batch


def test_tool_call_id_propagates_from_strategy_to_sse_events(monkeypatch):
    """End-to-end strategy-side check: when ``execute_tool_batch`` runs a
    tool with a known ``tc.id``, BOTH the emitted ``tool_start`` and
    ``tool_done`` SSE events MUST carry that exact id under
    ``data.tool_call_id``.

    The factory-level test ``test_tool_start_and_tool_done_carry_tool_call_id``
    only verified the HarnessEvent constructors do the right thing
    given an id. This test catches the regression case where
    ``tool_batch.py`` stops passing ``tool_call_id=tc.id`` to the
    factory — the factory test would still pass while the wire goes
    silently broken.
    """
    from app.agent_runtime.harness_events import HarnessEventType
    from app.agent_runtime.react_agent import AgentRunState
    from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    async def fake_dispatch(name, args, ctx):
        return {"ok": True}

    monkeypatch.setattr(
        "app.agent_runtime.tool_registry.registry.dispatch",
        fake_dispatch,
    )

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
        async for ev in execute_tool_batch(
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
    """Drive ``execute_tool_batch`` directly with a reasoning trace and
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
    from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    # Stub the inner tool-dispatch + persistence so execute_tool_batch can
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

    # project_oversized_result / enforce_turn_budget are imported into
    # the strategy module — patch at the use site.

    # Build the minimum input set for execute_tool_batch.
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
        async for _ in execute_tool_batch(
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
        async for _ in execute_tool_batch(
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


def test_concurrency_safe_tools_complete_live_and_replay_in_model_order(monkeypatch):
    """Independent reads overlap; SSE is live while replay stays model-ordered."""
    from app.agent_runtime.react_agent import AgentRunState
    from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
    from app.conversation.strategy import StrategyContext

    started: set[str] = set()
    both_started = asyncio.Event()
    active = 0
    max_active = 0

    class _Catalog:
        user_pk = 1

        def __contains__(self, name):
            return name in {"read_a", "read_b"}

        async def plan_call(self, name, arguments, _ctx):
            from app.agent_runtime.tool_policy import ToolEffect
            from app.agent_runtime.tool_registry import ToolDispatchPlan

            return ToolDispatchPlan(
                tool_name=name,
                arguments=arguments,
                effect=ToolEffect.READ,
                handler_exists=True,
                concurrency_safe=True,
            )

        def policy_traits(self, *_args):
            return False, False

        async def dispatch(self, name, _args, _ctx):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            started.add(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.5)
            if name == "read_a":
                await asyncio.sleep(0.02)
            active -= 1
            return {"tool": name}

    messages: list[dict] = []
    blocks: list[dict] = []
    events = []

    async def drain():
        async for event in execute_tool_batch(
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
    assert done_ids == ["c2", "c1"]


def test_batch_preflight_ask_starts_no_handler_in_batch_or_later(monkeypatch):
    from app.agent_runtime.react_agent import AgentRunState
    from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
    from app.agent_runtime.tool_policy import ToolEffect
    from app.agent_runtime.tool_registry import ToolDispatchPlan
    from app.conversation.strategy import StrategyContext

    dispatched: list[str] = []

    class _Catalog:
        user_pk = 1

        def __contains__(self, _name):
            return True

        async def plan_call(self, name, arguments, _ctx):
            return ToolDispatchPlan(
                tool_name=name,
                arguments=arguments,
                effect=ToolEffect.READ,
                handler_exists=True,
                concurrency_safe=True,
                connection_ready=name != "needs_connection",
            )

        def policy_traits(self, *_args):
            return False, False

        async def dispatch(self, name, _args, _ctx):
            dispatched.append(name)
            return {"tool": name}

    ctx = StrategyContext(user_id="alice", session_id="s1", user_message="run")
    events = []

    async def drain():
        async for event in execute_tool_batch(
            ctx=ctx,
            messages=[],
            blocks=[],
            tool_calls_acc=[
                _ToolCallAccumulator(id="c1", name="ready_sibling", arguments="{}"),
                _ToolCallAccumulator(id="c2", name="needs_connection", arguments="{}"),
                _ToolCallAccumulator(id="c3", name="later", arguments="{}"),
            ],
            assistant_content="",
            reasoning_content="",
            budget=AgentRunState(started_at=0.0),
            tool_catalog=_Catalog(),
        ):
            events.append(event)

    asyncio.run(drain())

    assert dispatched == []
    assert ctx.extras["interaction_required"]["tool_call_id"] == "c2"
    assert [
        event.data["tool_call_id"]
        for event in events
        if event.type.value == "tool_start"
    ] == ["c2"]


def test_same_resource_reads_are_split_into_serial_batches(monkeypatch):
    from app.agent_runtime.react_agent import AgentRunState
    from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
    from app.agent_runtime.tool_policy import ToolEffect
    from app.agent_runtime.tool_registry import ToolDispatchPlan
    from app.conversation.strategy import StrategyContext

    active = 0
    max_active = 0

    class _Catalog:
        user_pk = 1

        def __contains__(self, _name):
            return True

        async def plan_call(self, name, arguments, _ctx):
            return ToolDispatchPlan(
                tool_name=name,
                arguments=arguments,
                effect=ToolEffect.READ,
                handler_exists=True,
                concurrency_safe=True,
                resource_identities=frozenset({"account:one"}),
            )

        def policy_traits(self, *_args):
            return False, False

        async def dispatch(self, name, _args, _ctx):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"tool": name}

    async def drain():
        async for _ in execute_tool_batch(
            ctx=StrategyContext(user_id="alice", session_id="s1", user_message="read"),
            messages=[],
            blocks=[],
            tool_calls_acc=[
                _ToolCallAccumulator(id="c1", name="read_a", arguments="{}"),
                _ToolCallAccumulator(id="c2", name="read_b", arguments="{}"),
            ],
            assistant_content="",
            reasoning_content="",
            budget=AgentRunState(started_at=0.0),
            tool_catalog=_Catalog(),
        ):
            pass

    asyncio.run(drain())
    assert max_active == 1


class TestToolMetrics:
    """Tool execution must emit structured metrics via logger."""

    @pytest.mark.asyncio
    async def test_tool_metric_logged(self, monkeypatch):
        """execute_tool_batch must log tool_metric with latency and error status."""
        import logging

        async def fake_dispatch(name, args, ctx):
            return {"ok": True}

        monkeypatch.setattr(
            "app.agent_runtime.tool_registry.registry.dispatch",
            fake_dispatch,
        )

        from app.agent_runtime.react_agent import AgentRunState
        from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
        from app.conversation.strategy import StrategyContext

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
        target_logger = logging.getLogger("app.conversation.tool_batch")
        old_level = target_logger.level
        target_logger.setLevel(logging.DEBUG)
        target_logger.addHandler(handler)
        try:
            async for _ in execute_tool_batch(
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
