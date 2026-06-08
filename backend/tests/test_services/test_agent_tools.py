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


def test_recall_memory_returns_v3_bundle_keys(monkeypatch):
    """``recall_memory`` must surface the v3 return shape: user_profile +
    ability_states + learning_strategy_description + active_learning_strategy
    + ability_count. When ``load_strategy`` is set it pulls the full strategy
    body via ``attach_active_bodies``."""
    import asyncio

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import RecallMemoryArgs, _recall_memory_handler
    from app.services.memory.v3_context_loader import V3MemoryContext

    # Privacy gate open.
    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: True,
    )

    bundle = V3MemoryContext(
        user_profile_body="- 目标：后端岗位",
        ability_states=[
            {"topic": "Redis", "skill_type": "knowledge_topic",
             "mastery_level": "weak", "summary": "穿透没搞懂"},
        ],
        learning_strategy_description="先分析根因",
    )
    monkeypatch.setattr(
        "app.services.memory.v3_context_loader.load_universal",
        lambda user_id: bundle,
    )

    async def fake_attach(ctx, *, user_id, load_strategy=False):
        if load_strategy:
            ctx.active_learning_strategy_body = "- 先分析根因\n- 再给方案"
        return ctx

    monkeypatch.setattr(
        "app.services.memory.v3_context_loader.attach_active_bodies", fake_attach,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    out = asyncio.run(_recall_memory_handler(RecallMemoryArgs(load_strategy=True), ctx))

    assert out["user_profile"] == "- 目标：后端岗位"
    assert out["ability_states"][0]["topic"] == "Redis"
    assert out["learning_strategy_description"] == "先分析根因"
    assert "再给方案" in out["active_learning_strategy"]
    assert out["ability_count"] == 1
    # No old keys leak.
    assert "knowledge_topics" not in out
    assert "strategy_body" not in out


def test_recall_memory_disabled_when_global_memory_off(monkeypatch):
    """Privacy gate: when the global toggle is OFF the handler returns the
    disabled bundle and reads NO cross-session memory."""
    import asyncio

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import RecallMemoryArgs, _recall_memory_handler

    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: False,
    )

    def _boom(*a, **k):  # load_universal must NOT be called when disabled
        raise AssertionError("load_universal called despite memory toggle OFF")

    monkeypatch.setattr(
        "app.services.memory.v3_context_loader.load_universal", _boom,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    out = asyncio.run(_recall_memory_handler(RecallMemoryArgs(), ctx))
    assert out["disabled"] is True
    assert out["ability_count"] == 0


def test_save_memory_routes_target_to_v3_services(monkeypatch):
    """``save_memory`` dispatches by ``target``:
      * ability_state → memory_ability_state_service.upsert (topic/skill/level)
      * user_profile / learning_strategy → memory_document_service.apply_patches
    """
    import asyncio
    from dataclasses import dataclass

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import SaveMemoryArgs, _save_memory_handler

    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: True,
    )
    # The handler holds ``user_memory_lock`` — neutralise Redis dependence.
    import contextlib

    @contextlib.asynccontextmanager
    async def _noop_lock(user_id, **k):
        yield

    monkeypatch.setattr(
        "app.services.memory._user_memory_lock.user_memory_lock", _noop_lock,
    )

    ability_calls: list[dict] = []

    def fake_upsert(user_id, **kwargs):
        ability_calls.append({"user_id": user_id, **kwargs})
        return object()

    monkeypatch.setattr(
        "app.services.memory.memory_ability_state_service.upsert", fake_upsert,
    )

    @dataclass
    class _PR:
        applied: int = 1
        dropped: int = 0
        skipped: int = 0

    doc_calls: list[dict] = []

    def fake_apply(user_id, doc_type, patches, **kwargs):
        doc_calls.append({"user_id": user_id, "doc_type": doc_type, "patches": patches})
        return _PR()

    monkeypatch.setattr(
        "app.services.memory.memory_document_service.apply_patches", fake_apply,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")

    # ── ability_state target ──
    out = asyncio.run(_save_memory_handler(
        SaveMemoryArgs(
            target="ability_state", topic="Redis 缓存穿透",
            skill_type="knowledge_topic", mastery_level="weak",
            summary="不懂布隆过滤器",
        ),
        ctx,
    ))
    assert out["target"] == "ability_state"
    assert ability_calls and ability_calls[0]["topic"] == "Redis 缓存穿透"
    assert ability_calls[0]["skill_type"] == "knowledge_topic"
    assert ability_calls[0]["mastery_level"] == "weak"

    # ── learning_strategy target → doc apply_patches ──
    out = asyncio.run(_save_memory_handler(
        SaveMemoryArgs(target="learning_strategy", fact="先分析根因再给方案"),
        ctx,
    ))
    assert out["target"] == "learning_strategy"
    assert out["applied"] == 1
    assert doc_calls and doc_calls[-1]["doc_type"] == "learning_strategy"
    # The fact line is normalised into a markdown bullet patch.
    assert doc_calls[-1]["patches"][0]["new_line"].startswith("- 先分析根因")


def test_save_memory_rejects_unknown_target(monkeypatch):
    import asyncio

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import SaveMemoryArgs, _save_memory_handler

    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: True,
    )
    import contextlib

    @contextlib.asynccontextmanager
    async def _noop_lock(user_id, **k):
        yield

    monkeypatch.setattr(
        "app.services.memory._user_memory_lock.user_memory_lock", _noop_lock,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    out = asyncio.run(_save_memory_handler(
        SaveMemoryArgs(target="habit", fact="x"), ctx,
    ))
    assert "error" in out
    assert "ability_state" in out["valid"]


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

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.resume import _read_resume_handler, ReadResumeArgs

    # --- Common stubs -----------------------------------------------------

    # resume_service.get_sections_by_user returns [] so we always enter Tier 2.
    monkeypatch.setattr(
        "app.services.resume.resume_service.resume_service.get_sections_by_user",
        lambda user_id: [],
    )

    # Fake KnowledgeDocument rows. Branch behaviour is driven by the mocked
    # read_full_text_from_chunks return, not the row (the tool reads status,
    # title, id, created_at — never node_ids, which was dropped in 0024).
    class _FakeDoc:
        def __init__(self, *, id, title, status, created_at=None):
            self.id = id
            self.title = title
            self.status = status
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

    _TXT = "app.services.knowledge.knowledge_text_service.read_full_text_from_chunks"

    # --- Branch 1: chunks present → full_text --------------------------

    _patch_db([_FakeDoc(id="kdoc_X", title="resume.pdf", status="ready")])
    monkeypatch.setattr(
        _TXT,
        lambda doc, **k: ("孙根武\n北京邮电大学\n\n工作经历: ...\n\n技能: Python, Rust", 3),
    )
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "chunks_direct"
    assert result["node_count"] == 3
    assert "孙根武" in result["full_text"]
    assert "技能" in result["full_text"]
    assert result["full_text"].index("孙根武") < result["full_text"].index("工作经历")

    # --- Branch 2: no chunks yet → processing hint ---------------------

    _patch_db([_FakeDoc(id="kdoc_Y", title="resume.pdf", status="processing")])
    monkeypatch.setattr(_TXT, lambda doc, **k: ("", 0))
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "chunks_empty"
    assert result["status"] == "processing"
    assert "processing" in result["hint"].lower()

    # --- Branch 3: chunk read returns empty for a ready doc ------------

    _patch_db([_FakeDoc(id="kdoc_Z", title="resume.pdf", status="ready")])
    monkeypatch.setattr(_TXT, lambda doc, **k: ("", 0))
    result = asyncio.run(_read_resume_handler(args, ctx))
    assert result["source"] == "chunks_empty"
    assert "status=ready" in result["hint"]
    assert "no readable chunks" in result["hint"]


def test_tool_start_and_tool_done_carry_tool_call_id():
    """Both ``tool_start`` and ``tool_done`` SSE events must surface
    the LLM-assigned ``tool_call_id`` so the frontend can pair live-
    stream tool_use/tool_result blocks by id rather than FIFO order.
    The empty-default keeps the wire backwards-compatible with any
    older client that ignores the field.
    """
    from app.agent_runtime.harness_events import HarnessEvent

    start = HarnessEvent.tool_start(
        "search_jobs",
        "keywords=AI Agent",
        step=1, elapsed_ms=10.0,
        tool_call_id="call_AbC123",
    )
    assert start.to_dict()["data"]["tool_call_id"] == "call_AbC123"
    assert start.to_dict()["data"]["tool"] == "search_jobs"

    done = HarnessEvent.tool_done(
        "search_jobs", "返回 5 条结果",
        step=1, elapsed_ms=120.0,
        tool_latency_ms=80.0, is_error=False,
        result_content='{"count":5}',
        tool_call_id="call_AbC123",
    )
    assert done.to_dict()["data"]["tool_call_id"] == "call_AbC123"
    # Pairs with the start event by id.
    assert done.to_dict()["data"]["tool_call_id"] == start.to_dict()["data"]["tool_call_id"]

    # Back-compat: omitting tool_call_id yields the empty string, not
    # a missing key. The FE's ``String(data.tool_call_id ?? '')``
    # coerce always lands on a defined value.
    start_compat = HarnessEvent.tool_start(
        "x", "y", step=0, elapsed_ms=0.0,
    )
    assert start_compat.to_dict()["data"]["tool_call_id"] == ""
    done_compat = HarnessEvent.tool_done(
        "x", "y", step=0, elapsed_ms=0.0,
        tool_latency_ms=0.0, is_error=False,
    )
    assert done_compat.to_dict()["data"]["tool_call_id"] == ""


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
    import asyncio
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
    import asyncio

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


def test_session_scope_does_not_close_passed_session():
    """The ``session_scope`` helper's load-bearing contract:
       * db is None → open + close (auto-manage)
       * db is not None → yield, leave OPEN (caller-managed)

    Without this contract the P1-F shared-session plumbing breaks:
    the second ``.load(..., db=db)`` would hit a closed session and
    raise ``InvalidRequestError``. Indirect coverage via
    ``test_load_universal_opens_exactly_one_db_session`` only sees
    the 1-vs-4 count; this test pins the close-vs-stay-open behavior.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.services.memory._db_helpers import session_scope

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)

    # Branch 1: passing a session → helper must NOT close it.
    own = Session()
    try:
        with session_scope(own) as got:
            assert got is own
            assert own.is_active
        assert own.is_active, (
            "session_scope closed a passed-in session — breaks the "
            "P1-F shared-session contract that orchestrators rely on"
        )
    finally:
        own.close()
        engine.dispose()


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


def test_attach_active_bodies_yields_event_loop_via_to_thread(monkeypatch):
    """``attach_active_bodies`` is invoked via ``asyncio.create_task``
    in the engine, with the intent that the strategy-body load runs
    concurrently with the RAG knowledge_task. Pre-fix the function was
    ``async def`` around a fully synchronous body — calling it created
    a coroutine that ran top-to-bottom without ever yielding, so the
    "concurrent" knowledge_task never got loop time until memory
    finished.

    The v3 loader hydrates a single doc body (learning_strategy) via
    ``memory_document_service.load`` inside ``asyncio.to_thread``. We make
    that read block for 50ms; with the fix the sleep happens on a worker
    thread and a concurrent marker can complete in ~0ms, without the fix the
    main event loop is blocked for the full ~50ms before any other coroutine
    runs. The test detects this by WALL CLOCK rather than list order (an
    order-only check is tautological — the marker is scheduled first and
    yields at ``sleep(0)`` in both broken and fixed code).
    """
    import asyncio
    import time
    from app.services.memory.v3_context_loader import (
        V3MemoryContext, attach_active_bodies,
    )

    BLOCK_SECONDS = 0.05  # 50ms simulated DB read

    # ``**_`` swallows the ``db: Session | None`` kwarg the loader passes —
    # the test only cares about wall-clock blocking behavior.
    def sleepy_load(user_id, doc_type, **_):
        time.sleep(BLOCK_SECONDS)
        return "- some strategy body"

    monkeypatch.setattr(
        "app.services.memory.memory_document_service.load",
        sleepy_load,
    )

    timings: dict[str, float] = {}

    async def concurrent_marker(t0: float):
        # If attach_active_bodies properly yields the loop, this
        # coroutine gets driven during the sleep and ``marker`` time
        # registers near zero. If the loop is blocked, marker can't
        # run until bodies_task finishes — ≥ BLOCK_SECONDS later.
        await asyncio.sleep(0)
        timings["marker"] = time.perf_counter() - t0

    ctx_holder: dict[str, V3MemoryContext] = {}

    async def run():
        ctx = V3MemoryContext()
        ctx_holder["ctx"] = ctx
        t0 = time.perf_counter()
        marker_task = asyncio.create_task(concurrent_marker(t0))
        bodies_task = asyncio.create_task(
            attach_active_bodies(
                ctx, user_id="alice",
                load_strategy=True,    # 1 sleepy_load on a worker thread
            )
        )
        await bodies_task
        timings["bodies_done"] = time.perf_counter() - t0
        await marker_task

    asyncio.run(run())

    # With the fix, marker completes in ~0ms (sleep happens on a worker
    # thread). Without the fix, marker is blocked until bodies finishes
    # ~BLOCK_SECONDS in. Threshold at HALF the block budget gives plenty
    # of headroom for slow CI; on the failure side we'd see ~2x this.
    threshold = BLOCK_SECONDS / 2  # 25ms — well below BLOCK_SECONDS=50ms
    assert timings["marker"] < threshold, (
        f"attach_active_bodies didn't yield the event loop: "
        f"marker completed at {timings['marker']:.3f}s (threshold "
        f"{threshold:.3f}s; bodies_done at {timings['bodies_done']:.3f}s). "
        f"With the fix marker should complete in <10ms; the actual "
        f"value above means the main loop was blocked through the sync "
        f"DB read."
    )
    # And the body actually got hydrated (proves the load_strategy path ran).
    assert "strategy body" in ctx_holder["ctx"].active_learning_strategy_body


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
    import asyncio

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
