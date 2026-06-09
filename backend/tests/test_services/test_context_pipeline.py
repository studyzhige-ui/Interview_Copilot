"""SLOT_ORDER + renderer contract tests for the context pipeline."""
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    SLOT_ORDER,
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
        def get_recent_turns(self, **_kw):
            return []

    pipeline = ContextAssemblyPipeline()

    # Case 1 — debrief mode: auto-inject fires.
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript("debrief"))
    ctx = pipeline.assemble_answer_context(session_id="s1", current_query="q")
    assert ctx.debrief_reference == "[Manifest for ir_42]"
    assert ("ir_42", "alice") in fetch_calls
    fetch_calls.clear()

    # Case 2 — general mode: no fetch, slot stays empty.
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript("general"))
    ctx = pipeline.assemble_answer_context(session_id="s2", current_query="q")
    assert ctx.debrief_reference == ""
    assert fetch_calls == []

    # Case 3 — caller-supplied wins, no fetch even in debrief.
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript("debrief"))
    ctx = pipeline.assemble_answer_context(
        session_id="s1", current_query="q", debrief_reference="[Custom]"
    )
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

        def get_recent_turns(self, **_kw):
            return []

    pipeline = ContextAssemblyPipeline()
    monkeypatch.setattr(pipeline_mod, "transcript_service", FakeTranscript())

    ctx = pipeline.assemble_answer_context(session_id="s", current_query="q")
    assert ctx.summary == "## 当前状态\n聚焦 redis 缓存"

    rendered = pipeline.renderer.render_answer_prompt(ctx, system_prompt="rules")
    assert "[Context Summary]" in rendered
    assert "聚焦 redis 缓存" in rendered


# Note: ``assemble_rewrite_context`` was retired with the planner
# merge — the planner reads recent_turns directly via transcript_service
# now. See test_agent/test_planner.py for the planner-input contract tests.
