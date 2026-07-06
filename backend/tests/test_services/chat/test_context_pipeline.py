"""SLOT_ORDER + renderer contract tests for the context pipeline."""
import asyncio

from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    ContextAssemblyPipeline,
    PromptRenderer,
    SLOT_ORDER,
    TokenBudget,
)


def test_prompt_renderer_keeps_expected_slot_order():
    """Slots render in the cache-stable order: system → record → summary →
    recent turns → memory → retrieved → current (grounding at the tail)."""
    renderer = PromptRenderer()
    ctx = AssembledContext(
        debrief_reference="[Resume]\n张三",
        summary="focusing on redis",
        memory_block="# 用户画像\n- name: alice",
        retrieved_context="[K1] [interview_qa score=0.900] Redis cache avalanche.",
        recent_turns=[
            {"role": "User", "content": "What is cache avalanche?"},
            {"role": "Agent", "content": "It is a cache failure pattern."},
        ],
        current_input="How do I answer it in interviews?",
    )

    prompt = renderer.render_answer_prompt(ctx, system_prompt="System rules")

    # Authoritative order — all 7 slots in the correct positions.
    indices = [
        prompt.index("System rules"),
        prompt.index("[Record Context]"),
        prompt.index("[Context Summary]"),
        prompt.index("[Recent Turns]"),
        prompt.index("[Memory]"),
        prompt.index("[Retrieved Context]"),
        prompt.index("[Current Query]"),
    ]
    assert indices == sorted(indices), (
        f"Slot order broke. Expected ascending positions, got {indices}"
    )


def test_renderer_skips_empty_slots():
    """A slot with no content (empty string / list / dict) must NOT
    emit its [Tag] header — otherwise the LLM sees a confusing
    placeholder. Also: system_prompt has tag=None so the rendered
    output starts with the raw rules text, no header prefix."""
    renderer = PromptRenderer()
    ctx = AssembledContext(
        memory_block="# Memory bundle",
        current_input="hi",
    )
    prompt = renderer.render_answer_prompt(ctx, system_prompt="rules")

    # system_prompt slot has no [Tag] — raw text leads the prompt.
    assert prompt.startswith("rules"), (
        f"system_prompt should render without a tag header; got {prompt[:60]!r}"
    )
    assert "[Memory]" in prompt
    assert "[Record Context]" not in prompt        # debrief slot empty
    assert "[Retrieved Context]" not in prompt     # no RAG
    assert "[Context Summary]" not in prompt       # no summary
    assert "[Recent Turns]" not in prompt          # empty list


def test_slot_order_has_no_duplicate_fields():
    """SLOT_ORDER is the single source of truth — make sure no field
    is listed twice (would silently double-render that slot)."""
    fields = [entry[0] for entry in SLOT_ORDER]
    assert len(fields) == len(set(fields)), (
        f"Duplicate field in SLOT_ORDER: {fields}"
    )


def test_rewrite_context_skips_heavy_slots():
    """``render_context_text`` is the planner's input. It must NOT
    include memory_block, retrieved_context, or system_prompt —
    they're useless for query rewriting and would balloon the
    planner's prompt for no reason."""
    renderer = PromptRenderer()
    ctx = AssembledContext(
        system_prompt="should not appear",
        memory_block="should not appear",
        retrieved_context="should not appear",
        summary="prior conversation summary",
        recent_turns=[{"role": "User", "content": "earlier message"}],
        current_input="follow-up",
    )
    out = renderer.render_context_text(ctx)
    assert "should not appear" not in out
    assert "[Context Summary]" in out
    assert "[Recent Turns]" in out
    assert "[Current Query]" in out


# ── Debrief auto-inject contract ──────────────────────────────────────


def test_debrief_reference_auto_inject_fires_only_in_debrief_mode(monkeypatch):
    """The pipeline auto-injects an interview reference IFF the
    session is debrief mode AND has an interview_id. Non-debrief
    sessions (general / mock_interview) must NEVER trigger the SQL
    fetch — otherwise we leak reference material into chats that
    aren't supposed to see it."""
    from app.services.chat import context_assembly_pipeline as pipeline_mod
    from app.services.chat.context_assembly_pipeline import ContextAssemblyPipeline

    fetch_calls: list[tuple[str, str]] = []

    def fake_build(interview_id, user_id):
        fetch_calls.append((interview_id, user_id))
        return f"[Manifest for {interview_id}]"

    # Patch the lazy import target.
    import app.services.chat.interview_reference as ir_mod
    monkeypatch.setattr(ir_mod, "build_interview_reference", fake_build)

    # Stub transcript_service for both meta + recent turns.
    class FakeTranscript:
        def __init__(self, mode: str):
            self.mode = mode
        def get_session_meta(self, session_id):
            return {
                "session_id": session_id,
                "user_id": "alice",
                "type": self.mode,
                "subject_type": "interview_record" if self.mode != "general" else None,
                "subject_id": "ir_42" if self.mode != "general" else None,
                "compaction_cursor": 0,
            }
        def get_turns_after(self, session_id, after_seq=0):
            return []

    pipeline = ContextAssemblyPipeline()

    # Case 1 — debrief mode: auto-inject fires.
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript("debrief"))
    ctx = asyncio.run(pipeline.assemble_answer_context(session_id="s1", current_query="q"))
    assert ctx.debrief_reference == "[Manifest for ir_42]"
    assert ("ir_42", "alice") in fetch_calls
    fetch_calls.clear()

    # Case 2 — general mode: no fetch, slot stays empty.
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript("general"))
    ctx = asyncio.run(pipeline.assemble_answer_context(session_id="s2", current_query="q"))
    assert ctx.debrief_reference == ""
    assert fetch_calls == []

    # Case 3 — caller-supplied wins, no fetch even in debrief.
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript("debrief"))
    ctx = asyncio.run(pipeline.assemble_answer_context(
        session_id="s1", current_query="q", debrief_reference="[Custom]"
    ))
    assert ctx.debrief_reference == "[Custom]"
    assert fetch_calls == []


def test_summary_comes_from_summary_column(monkeypatch):
    """The [Context Summary] slot is sourced from the dedicated ``summary``
    column (get_session_meta['summary']) — the sole source."""
    from app.services.chat import context_assembly_pipeline as pipeline_mod
    from app.services.chat.context_assembly_pipeline import ContextAssemblyPipeline

    class FakeTranscript:
        def get_session_meta(self, session_id):
            return {
                "session_id": session_id,
                "user_id": "alice",
                "type": "general",
                "subject_type": None,
                "subject_id": None,
                "turn_count": 0,
                "compaction_cursor": 0,
                "memory_extraction_cursor": 0,
                "summary": "## 当前状态\n聚焦 redis 缓存",      # dedicated column
            }

        def get_turns_after(self, session_id, after_seq=0):
            return []

    pipeline = ContextAssemblyPipeline()
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript())

    ctx = asyncio.run(pipeline.assemble_answer_context(session_id="s", current_query="q"))
    assert ctx.summary == "## 当前状态\n聚焦 redis 缓存"

    rendered = pipeline.renderer.render_answer_prompt(ctx, system_prompt="rules")
    assert "[Context Summary]" in rendered
    assert "聚焦 redis 缓存" in rendered


# ── Full-history context (no fixed window) ────────────────────────────


def test_assemble_loads_all_turns_after_cursor(monkeypatch):
    """The pipeline loads ALL turns after the compaction cursor, not a
    fixed 20-turn window. This is the incremental-append model."""
    from app.services.chat import context_assembly_pipeline as pipeline_mod
    from app.services.chat.context_assembly_pipeline import ContextAssemblyPipeline

    turns = [
        {"seq": i, "role": "User" if i % 2 else "Agent", "content": f"msg {i}"}
        for i in range(1, 51)  # 50 messages — well beyond the old 20-turn cap
    ]

    class FakeTranscript:
        def get_session_meta(self, session_id):
            return {
                "user_id": "alice", "type": "general", "subject_type": None,
                "subject_id": None, "compaction_cursor": 0, "summary": "",
            }
        def get_turns_after(self, session_id, after_seq=0):
            return [t for t in turns if t["seq"] > after_seq]

    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript())
    pipeline = ContextAssemblyPipeline()
    ctx = asyncio.run(pipeline.assemble_answer_context(session_id="s", current_query="q"))

    # All 50 messages should be present (after sanitize + repair_pairs
    # drops the leading Agent and trailing User if needed).
    assert len(ctx.recent_turns) >= 48


# ── Threshold-based compaction ─────────────────────────────────────────


def test_threshold_compaction_fires_and_advances_cursor(monkeypatch):
    """When assembled context exceeds the threshold, compaction fires:
    old turns are summarized, cursor advances, and only protected tail
    turns remain verbatim."""
    from app.services.chat import context_assembly_pipeline as pipeline_mod
    from app.services.chat.context_assembly_pipeline import ContextAssemblyPipeline, TokenBudget

    updates: list[dict] = []

    # Build turns that exceed the threshold.
    big_content = "x " * 500  # ~500 tokens each
    turns = []
    for i in range(1, 21):
        role = "User" if i % 2 == 1 else "Agent"
        turns.append({"seq": i, "role": role, "content": big_content})

    class FakeTranscript:
        def get_session_meta(self, session_id):
            return {
                "user_id": "alice", "type": "general", "subject_type": None,
                "subject_id": None, "compaction_cursor": 0, "summary": "",
            }
        def get_turns_after(self, session_id, after_seq=0):
            return [t for t in turns if t["seq"] > after_seq]
        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    # Stub summarize_conversation to return a fixed summary.
    import app.services.memory.compaction_service as cs_mod
    monkeypatch.setattr(cs_mod, "summarize_conversation",
        lambda old, conv: asyncio.coroutine(lambda: "COMPRESSED SUMMARY")(old, conv)
    )
    # Use a proper async stub
    async def fake_summarize(old, conv, *, user_id=None):
        return "COMPRESSED SUMMARY"
    monkeypatch.setattr(cs_mod, "summarize_conversation", fake_summarize)

    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript())

    # Use a tiny threshold so compaction triggers.
    budget = TokenBudget()
    budget.MODEL_CONTEXT_WINDOW = 2_000
    budget.COMPRESS_THRESHOLD_RATIO = 0.5  # 1000 tokens threshold
    pipeline = ContextAssemblyPipeline(budget=budget)

    ctx = asyncio.run(pipeline.assemble_answer_context(session_id="s", current_query="q"))

    # Compaction should have fired — cursor advanced, summary updated.
    assert len(updates) == 1
    assert "summary" in updates[0]
    assert updates[0]["summary"] == "COMPRESSED SUMMARY"
    assert "compaction_cursor" in updates[0]
    # Protected tail (COMPRESS_PROTECT_LAST_N=4) should remain.
    assert len(ctx.recent_turns) <= budget.COMPRESS_PROTECT_LAST_N
    assert ctx.summary == "COMPRESSED SUMMARY"


def test_no_compaction_when_under_threshold(monkeypatch):
    """Short conversations should pass through without compaction."""
    from app.services.chat import context_assembly_pipeline as pipeline_mod
    from app.services.chat.context_assembly_pipeline import ContextAssemblyPipeline

    updates: list[dict] = []
    turns = [
        {"seq": 1, "role": "User", "content": "hi"},
        {"seq": 2, "role": "Agent", "content": "hello"},
    ]

    class FakeTranscript:
        def get_session_meta(self, session_id):
            return {
                "user_id": "alice", "type": "general", "subject_type": None,
                "subject_id": None, "compaction_cursor": 0, "summary": "",
            }
        def get_turns_after(self, session_id, after_seq=0):
            return [t for t in turns if t["seq"] > after_seq]
        def update_session_fields(self, session_id, **kwargs):
            updates.append(kwargs)

    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript())
    pipeline = ContextAssemblyPipeline()
    ctx = asyncio.run(pipeline.assemble_answer_context(session_id="s", current_query="q"))

    assert len(ctx.recent_turns) == 2
    assert updates == []  # no compaction triggered
    assert ctx.summary == ""


# ── [K#] numbering + sources building (context assembly is the sole owner) ──


def _chunk(node_id: str, text: str, **over) -> dict:
    base = {
        "chunk_id": f"dch_{node_id}",
        "node_id": node_id,
        "document_id": "kdoc_1",
        "document_title": "Redis 面试题",
        "file_name": "redis.pdf",
        "category": "面试题库",
        "source_kind": "user_upload",
        "page_start": None,
        "page_end": None,
        "section_title": None,
        "heading_path": None,
        "chunk_index": 0,
        "score": 0.87,
        "score_source": "reranker",
        "text": text,
    }
    base.update(over)
    return base


def test_build_retrieved_context_numbers_and_aligns_sources():
    pipeline = ContextAssemblyPipeline()
    chunks = [
        _chunk("n1", "Redis 缓存击穿……", page_start=3, page_end=3, chunk_index=12),
        _chunk("n2", "缓存穿透……", section_title="缓存异常场景", chunk_index=4, score=0.82),
    ]
    text, sources = pipeline._build_retrieved_context(chunks)

    # [K#] refs are 1-based and contiguous, in rank order.
    assert text.startswith("[K1]")
    assert "[K2]" in text
    assert [s["ref"] for s in sources] == ["K1", "K2"]
    # Header carries the lightweight provenance hint.
    assert 'title="Redis 面试题"' in text
    assert "page=3" in text
    assert 'section="缓存异常场景"' in text
    assert "chunk=12" in text
    assert "score=0.870" in text
    # Sources align 1:1 and carry the full §2.7 schema.
    s1 = sources[0]
    assert s1["chunk_id"] == "dch_n1"
    assert s1["node_id"] == "n1"
    assert s1["document_title"] == "Redis 面试题"
    assert s1["file_name"] == "redis.pdf"
    assert s1["page_start"] == 3
    assert s1["score_source"] == "reranker"
    assert s1["text_preview"].startswith("Redis 缓存击穿")


def test_build_retrieved_context_page_range_header():
    pipeline = ContextAssemblyPipeline()
    text, _ = pipeline._build_retrieved_context(
        [_chunk("n1", "x", page_start=3, page_end=5)]
    )
    assert "page=3-5" in text


def test_build_retrieved_context_empty():
    pipeline = ContextAssemblyPipeline()
    assert pipeline._build_retrieved_context([]) == ("", [])
    assert pipeline._build_retrieved_context(None) == ("", [])


def test_build_retrieved_context_skips_blank_text_chunks():
    pipeline = ContextAssemblyPipeline()
    text, sources = pipeline._build_retrieved_context(
        [_chunk("n1", ""), _chunk("n2", "real content")]
    )
    # The blank chunk takes no ref; the next real chunk is K1, not K2.
    assert [s["ref"] for s in sources] == ["K1"]
    assert sources[0]["node_id"] == "n2"


def test_build_retrieved_context_truncates_single_oversized_chunk():
    budget = TokenBudget()
    budget.RETRIEVED_CONTEXT_BUDGET = 20
    pipeline = ContextAssemblyPipeline(budget=budget)
    big = "缓存 " * 200
    text, sources = pipeline._build_retrieved_context([_chunk("n1", big)])

    assert len(sources) == 1
    assert sources[0].get("truncated") is True


def test_build_retrieved_context_stops_at_budget():
    budget = TokenBudget()
    budget.RETRIEVED_CONTEXT_BUDGET = 30
    pipeline = ContextAssemblyPipeline(budget=budget)
    chunks = [_chunk(f"n{i}", "缓存雪崩的解决方案包括过期时间随机化。" * 2) for i in range(5)]
    _, sources = pipeline._build_retrieved_context(chunks)

    # First chunk always lands; later chunks stop once the budget is hit.
    assert 1 <= len(sources) < 5


def test_assemble_answer_context_populates_sources(monkeypatch):
    from app.services.chat import context_assembly_pipeline as pipeline_mod
    from app.services.chat.context_assembly_pipeline import ContextAssemblyPipeline

    class FakeTranscript:
        def get_session_meta(self, session_id):
            return {
                "user_id": "alice", "type": "general", "subject_type": None,
                "subject_id": None, "compaction_cursor": 0, "summary": "",
            }

        def get_turns_after(self, session_id, after_seq=0):
            return []

    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript())
    pipeline = ContextAssemblyPipeline()

    ctx = asyncio.run(pipeline.assemble_answer_context(
        session_id="s", current_query="q",
        knowledge_chunks=[_chunk("n1", "Redis 缓存击穿……")],
    ))
    assert ctx.sources and ctx.sources[0]["ref"] == "K1"
    assert "[K1]" in ctx.retrieved_context


# Note: ``assemble_rewrite_context`` was retired with the planner
# merge — the planner reads recent_turns directly via transcript_service
# now. See test_agent/test_planner.py for the planner-input contract tests.
