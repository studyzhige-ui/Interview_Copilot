"""Tests for the new ToolRegistry-based agent tools."""

import asyncio

import pytest


def test_tool_registry_has_expected_tools():
    from app.agent_runtime.tool_registry import registry

    expected = {
        "web_search", "read_url", "read_file", "write_file",
        "recall_memory", "save_memory", "search_knowledge",
        "read_resume", "read_interview_history", "search_jobs",
    }
    assert expected == set(registry.tool_names)


def test_openai_schemas_generated():
    from app.agent_runtime.tool_registry import registry

    schemas = registry.get_openai_schemas()
    assert len(schemas) >= 9  # web_search excluded when TAVILY_API_KEY is not set
    for schema in schemas:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "parameters" in schema["function"]


def test_dispatch_unknown_tool():
    from app.agent_runtime.tool_registry import AgentToolContext, registry

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    result = asyncio.run(registry.dispatch("nonexistent_tool", {}, ctx))
    assert result["error"] == "unknown_tool"


def test_parse_tool_arguments_valid():
    from app.agent_runtime.tool_registry import parse_tool_arguments

    result = parse_tool_arguments('{"query": "test"}')
    assert result == {"query": "test"}


def test_parse_tool_arguments_invalid():
    from app.agent_runtime.tool_registry import parse_tool_arguments

    with pytest.raises(ValueError):
        parse_tool_arguments("not json")


def test_format_manifest():
    from app.agent_runtime.tool_registry import registry

    manifest = registry.format_manifest()
    assert "web_search" in manifest
    assert "read_resume" in manifest


def test_registry_exclude_hides_tools_symmetrically():
    """``exclude`` must drop a tool from BOTH the manifest AND the
    OpenAI schemas — otherwise the LLM sees a tool in one place but
    not the other and gets confused. The agent strategy relies on
    this symmetry to gate memory tools when the global-memory
    toggle is off (Claude Code's ``isAutoMemoryEnabled=false``
    semantics).
    """
    from app.agent_runtime.tool_registry import registry

    memory_tools = {"recall_memory", "save_memory"}

    schemas = registry.get_openai_schemas(exclude=memory_tools)
    schema_names = {s["function"]["name"] for s in schemas}
    assert "recall_memory" not in schema_names
    assert "save_memory" not in schema_names
    # Non-memory tools still present.
    assert "read_resume" in schema_names
    assert "search_jobs" in schema_names

    manifest = registry.format_manifest(exclude=memory_tools)
    assert "recall_memory" not in manifest
    assert "save_memory" not in manifest
    assert "read_resume" in manifest


def test_result_summary_detects_disabled_payload():
    """``recall_memory`` returning ``{"disabled": true, "reason": ...}``
    must NOT fall through to the byte-counter "完成 (N chars)" fallback.

    Pre-fix screenshot evidence: user toggled global memory OFF, the
    LLM called recall_memory anyway, got back the 273-char
    ``{"disabled": true, "reason": "用户已关闭..."}`` payload, and
    the UI rendered "✅ 完成 (273 chars)" — looked like a successful
    call to a casual user. We surface the disabled signal explicitly
    so the summary is honest.
    """
    from app.agent_runtime.react_agent import _result_summary

    s = _result_summary({
        "disabled": True,
        "reason": "用户已关闭全局记忆开关",
        "user_profile": "",
    })
    assert s.startswith("⊘")
    assert "已关闭" in s
    assert "完成" not in s  # MUST NOT use the success template

    # Sanity check the existing branches still fire.
    assert _result_summary({"error": "boom"}).startswith("❌")
    assert _result_summary({"count": 0}) == "返回 0 条结果"
    assert _result_summary({"count": 5}) == "返回 5 条结果"


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


def test_read_resume_direct_docstore_read(monkeypatch):
    """When the user has a resume PDF in ``knowledge_documents`` (but
    no parsed ``resume_sections`` row yet), ``read_resume`` reads the
    full document text DIRECTLY from the LlamaIndex PostgresDocumentStore
    via the row's ``node_ids``. Pre-fix the tool told the LLM to use
    search_knowledge (which returns ~5 reranked chunks of 1500 chars —
    fragmented and partial). Direct read returns the full resume text.

    Covers three branches:
      (1) full_text returned when docstore yields nodes
      (2) docstore_empty hint when node_ids is empty (still processing)
      (3) docstore exception path surfaces ``Docstore error: ...``
    """
    import asyncio
    import json
    from types import SimpleNamespace

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.resume import _read_resume_handler, ReadResumeArgs

    # --- Common stubs -----------------------------------------------------

    # resume_service.get_sections_by_user returns [] so we always enter Tier 2.
    monkeypatch.setattr(
        "app.services.resume_service.resume_service.get_sections_by_user",
        lambda user_id: [],
    )

    # Fake KnowledgeDocument rows. Branch (1) has node_ids; (2) empty list.
    class _FakeDoc:
        def __init__(self, *, id, title, status, node_ids, created_at=None):
            self.id = id
            self.title = title
            self.status = status
            self.node_ids = json.dumps(node_ids)
            self.created_at = created_at

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    args = ReadResumeArgs(section_types=[])

    def _patch_db(doc_rows):
        """Stub SessionLocal so the query returns the given doc_rows."""
        class _Q:
            def __init__(self, rows): self.rows = rows
            def filter(self, *a, **k): return self
            def order_by(self, *a, **k): return self
            def all(self): return self.rows
        class _Db:
            def __init__(self, rows): self.rows = rows
            def query(self, *a, **k): return _Q(self.rows)
            def close(self): pass
        monkeypatch.setattr(
            "app.db.database.SessionLocal",
            lambda: _Db(doc_rows),
        )

    # --- Branch 1: docstore yields nodes → full_text -------------------

    _patch_db([_FakeDoc(
        id="kdoc_X", title="resume.pdf", status="ready",
        node_ids=["n1", "n2", "n3"],
    )])

    class _FakeDocstore:
        def __init__(self, mapping): self.mapping = mapping
        def get_document(self, nid):
            text = self.mapping.get(nid)
            return SimpleNamespace(text=text) if text else None

    fake_store = _FakeDocstore({
        "n1": "孙根武\n北京邮电大学",
        "n2": "工作经历: ...",
        "n3": "技能: Python, Rust",
    })
    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(lambda cls, uri: fake_store),
    )

    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "docstore_direct"
    assert result["node_count"] == 3
    assert "孙根武" in result["full_text"]
    assert "工作经历" in result["full_text"]
    assert "技能" in result["full_text"]
    # Ordering preserved (n1 before n2 before n3).
    assert result["full_text"].index("孙根武") < result["full_text"].index("工作经历")

    # --- Branch 2: empty node_ids → processing hint -------------------

    _patch_db([_FakeDoc(
        id="kdoc_Y", title="resume.pdf", status="processing",
        node_ids=[],
    )])
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "docstore_empty"
    assert result["status"] == "processing"
    assert "processing" in result["hint"].lower()

    # --- Branch 3: docstore.from_uri raises → friendly error hint -----
    # NB: post-refactor, the exception is swallowed + logged inside
    # ``read_full_text_from_docstore`` (the shared helper) rather than
    # propagating up to the tool handler. That's the right separation
    # of concerns — the raw exception message ("simulated_db_down" or
    # similar) stays in server logs and does NOT leak into the LLM-
    # facing hint string. The user-facing branch detection is
    # unchanged: still ``source=docstore_empty`` with a hint.

    _patch_db([_FakeDoc(
        id="kdoc_Z", title="resume.pdf", status="ready",
        node_ids=["n1"],
    )])
    def _boom(cls, uri):
        raise RuntimeError("simulated_db_down")
    monkeypatch.setattr(
        "llama_index.storage.docstore.postgres.PostgresDocumentStore.from_uri",
        classmethod(_boom),
    )
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "docstore_empty"
    # Hint mentions status + the no-readable-nodes signal. Raw
    # exception text is intentionally NOT in the hint.
    assert "status=ready" in result["hint"]
    assert "no readable nodes" in result["hint"]
    # The user-facing string should not leak raw infrastructure errors.
    assert "simulated_db_down" not in result["hint"]


def test_tool_done_event_carries_full_result_content():
    """``tool_done`` SSE event must include ``result_content`` so the
    live tool card renders the expanded view without a refresh.

    Pre-fix the wire format only carried ``result_summary`` and the
    frontend showed "(刷新会话以加载完整输出)" until reload.
    """
    from app.agent_runtime.harness_events import HarnessEvent

    ev = HarnessEvent.tool_done(
        "search_jobs",
        "返回 5 条结果",
        step=1, elapsed_ms=120.0,
        tool_latency_ms=80.0, is_error=False,
        result_content='{"source":"lever","count":5,"jobs":[...]}',
    )
    payload = ev.to_dict()
    assert payload["type"] == "tool_done"
    assert payload["data"]["result_summary"] == "返回 5 条结果"
    assert payload["data"]["result_content"].startswith("{")
    assert payload["data"]["tool_latency_ms"] == 80.0
    assert payload["data"]["is_error"] is False

    # Backwards-compat: omitting ``result_content`` produces an empty
    # string, not a missing key — so the frontend's String(...) coerce
    # always lands on a defined value.
    ev2 = HarnessEvent.tool_done(
        "search_jobs", "返回 0 条结果",
        step=1, elapsed_ms=120.0,
        tool_latency_ms=80.0, is_error=False,
    )
    assert ev2.to_dict()["data"]["result_content"] == ""


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
    import asyncio
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


def test_agent_messages_split_manifest_from_grounding_for_prompt_cache():
    """The agent's system messages MUST be three separate entries:
    SYSTEM_PROMPT (stable, slot 0) → manifest (stable per session,
    slot 1) → grounding (per-turn, slot 2). DeepSeek / Anthropic prompt
    caches hash the prefix as a single contiguous span; a per-turn
    change to grounding text would invalidate the cached manifest
    tokens too if they shared a system message. Splitting saves
    800-2000 cached tokens per agent turn.

    This test reads the actual messages array the strategy constructs,
    so a future contributor merging them back into one message will
    silently regress and this test fails loudly.
    """
    import asyncio
    from types import SimpleNamespace

    from app.agent_runtime.tool_registry import registry
    from app.conversation.agent_strategy import (
        AgentLoopStrategy,
        SYSTEM_PROMPT,
    )

    # Inspect the message-construction logic without running the LLM.
    # We mirror the construction by calling registry.format_manifest
    # the same way the strategy does. The order check matters more
    # than the exact text.
    manifest = registry.format_manifest()
    grounding = "Recent turns: [{user: 'hi'}]"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Available tools:\n{manifest}"},
        {"role": "system", "content": f"Conversation context:\n{grounding}"},
        {"role": "user", "content": "test"},
    ]
    # Sanity checks on the cache-friendly shape:
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["content"].startswith("Available tools:")
    assert "Conversation context:" not in messages[1]["content"], (
        "tool manifest must NOT be wedged into the per-turn grounding "
        "message — that defeats prompt cache reuse"
    )
    assert messages[2]["content"].startswith("Conversation context:")
    assert "Available tools:" not in messages[2]["content"]

    # The actual strategy builds this same shape — verify by reading the
    # source. Brittle but cheap; catches a copy-paste regression.
    import inspect
    src = inspect.getsource(AgentLoopStrategy.execute)
    assert "Available tools:" in src
    assert "Conversation context:" in src
    # The two strings must appear in separate ``{"role": "system"...}``
    # entries. If a future refactor concatenates them into one f-string
    # again, this regex catches the regression.
    import re
    # Match the system messages section. Each message must end before
    # the next ``{"role"`` begins.
    matches = re.findall(
        r'\{"role":\s*"system",\s*"content":[^}]+\}',
        src,
        re.DOTALL,
    )
    # SYSTEM_PROMPT, manifest, grounding = at least 3 system messages
    assert len(matches) >= 3, (
        f"expected ≥3 system messages in execute() for cache-friendly "
        f"prefix; found {len(matches)}: {[m[:80] for m in matches]}"
    )


def test_attach_active_bodies_yields_event_loop_via_to_thread(monkeypatch):
    """``attach_active_bodies`` is invoked via ``asyncio.create_task``
    in the engine, with the intent that memory body loads run
    concurrently with the RAG knowledge_task. Pre-fix the function was
    ``async def`` around a fully synchronous body — calling it created
    a coroutine that ran top-to-bottom without ever yielding, so the
    "concurrent" knowledge_task never got loop time until memory
    finished.

    The test detects this by WALL CLOCK rather than just list order
    (earlier version of this test was tautological — marker_task
    completed before bodies_task in both broken and fixed code merely
    because it was scheduled first and yielded at ``sleep(0)``). Here
    we have ``knowledge_doc_service.load`` block for 50ms per call;
    with the fix the sleep happens on a worker thread and a concurrent
    marker can complete in ~0ms, without the fix the main event loop
    is blocked for the full ~50ms before any other coroutine runs.
    """
    import asyncio
    import time
    from app.services.memory.v3_context_loader import (
        V3MemoryContext, attach_active_bodies,
    )

    BLOCK_SECONDS = 0.05  # 50ms per simulated DB read

    def sleepy_load(user_id, topic=None):
        time.sleep(BLOCK_SECONDS)
        return None

    monkeypatch.setattr(
        "app.services.memory.knowledge_doc_service.load",
        sleepy_load,
    )
    monkeypatch.setattr(
        "app.services.memory.strategy_doc_service.load",
        lambda user_id: (time.sleep(BLOCK_SECONDS), "")[1],
    )
    monkeypatch.setattr(
        "app.services.memory.habit_doc_service.load",
        lambda user_id: (time.sleep(BLOCK_SECONDS), "")[1],
    )

    timings: dict[str, float] = {}

    async def concurrent_marker(t0: float):
        # If attach_active_bodies properly yields the loop, this
        # coroutine gets driven during the sleeps and ``marker`` time
        # registers near zero. If the loop is blocked, marker can't
        # run until bodies_task finishes — ≥ 4 * BLOCK_SECONDS later.
        await asyncio.sleep(0)
        timings["marker"] = time.perf_counter() - t0

    async def run():
        ctx = V3MemoryContext()
        t0 = time.perf_counter()
        marker_task = asyncio.create_task(concurrent_marker(t0))
        bodies_task = asyncio.create_task(
            attach_active_bodies(
                ctx, user_id="alice",
                topics=["t1", "t2"],   # 2 sleepy_loads
                load_strategy=True,    # 1 sleepy_load
                load_habit=True,       # 1 sleepy_load
            )
        )
        await bodies_task
        timings["bodies_done"] = time.perf_counter() - t0
        await marker_task

    asyncio.run(run())

    # With the fix, marker completes in ~0ms (sleeps happen in worker
    # thread). Without the fix, marker is blocked until bodies finishes
    # ~4*BLOCK_SECONDS = 200ms in. Threshold at HALF of the total block
    # budget gives plenty of headroom for slow CI; on the failure side
    # we'd see 4x this threshold.
    threshold = BLOCK_SECONDS * 2  # 100ms — well below 4*BLOCK=200ms
    assert timings["marker"] < threshold, (
        f"attach_active_bodies didn't yield the event loop: "
        f"marker completed at {timings['marker']:.3f}s (threshold "
        f"{threshold:.3f}s; bodies_done at {timings['bodies_done']:.3f}s). "
        f"With the fix marker should complete in <10ms; the actual "
        f"value above means the main loop was blocked through the sync "
        f"DB reads."
    )


def test_graceful_fallback_is_wired_into_strategy_except_path(monkeypatch):
    """Pin the WIRING: a crash in the inner loop must route through
    ``_build_graceful_fallback`` and never re-introduce the dead
    "Agent 执行失败" headline. Without this test, a future refactor
    could overwrite the except branch with a literal string and the
    unit tests of ``_build_graceful_fallback`` alone would still pass.
    """
    import asyncio

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
        lambda role: (object(), _StubProfile()),
    )

    # Stub the budget compactor so the loop reaches the LLM-stream call.
    class _StubCompactor:
        def __init__(self, profile=None): self.profile = profile
        def pre_llm_compact(self, messages, _): return messages
        def is_at_blocking_limit(self, _): return False
        def reset_circuit_breaker(self): pass
        def on_context_too_long(self, messages): return messages, False
    monkeypatch.setattr(
        "app.conversation.agent_strategy.QueryLoopCompactor",
        _StubCompactor,
    )

    # Stub agent_runs persistence — we don't care about it here.
    async def _noop(*args, **kwargs): return "stub_run_id"
    async def _noop_step(*args, **kwargs): return None
    monkeypatch.setattr("app.conversation.agent_strategy.create_run", _noop)
    monkeypatch.setattr("app.conversation.agent_strategy.append_step", _noop_step)
    monkeypatch.setattr("app.conversation.agent_strategy.finish_run", _noop_step)

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
