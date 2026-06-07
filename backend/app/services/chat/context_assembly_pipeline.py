"""Context assembly pipeline — slot-based prompt composition.

Builds the LLM prompt for a chat / agent turn by populating named
slots, then rendering them in a single authoritative order. Slot
ordering is chosen for prompt-cache friendliness — most-stable
content at the top, per-turn content at the bottom.

Slots, in order from most → least cache-stable:

  1. (System Prompt)       caller-supplied (chat / RAG / agent prompt; the
                           agent's includes the tool manifest). Rendered raw,
                           no [Tag] header.
  2. [Record Context]      debrief sessions only — interview reference
                           manifest (resume + JD + analysis summary). Stable
                           for the duration of one debrief.
  3. [Context Summary]     compaction summary (from the ``summary`` column);
                           changes only when a compaction fires.
  4. [Recent Turns]        most recent user↔agent dialogue pairs (append-only).
  5. [Memory]              v3 memory bundle (per-turn-variable grounding);
                           user_profile is ALWAYS the first sub-section.
  6. [Retrieved Context]   RAG knowledge chunks (per-turn-variable grounding).
  7. [Current Query]       the user's standalone (rewritten) question.

Per-turn-variable grounding (memory + RAG) sits near the tail so a grounding
change can't invalidate the cached stable prefix (summary + recent turns).

A single :data:`SLOT_ORDER` constant is the SOLE place that decides
slot ordering — both the answer-prompt renderer and the lightweight
rewrite-context renderer iterate it. Adding a slot is one tuple
entry plus a matching field on :class:`AssembledContext`; no second
ordering definition to keep in sync.

This module is distinct from
``app.agent_runtime.context_compactor.QueryLoopCompactor``, which
compresses the running message list inside a single L2 agent
execution (different problem, different file).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from app.agent_runtime.context_manager import token_count as count_tokens
from app.services.chat.chat_history_service import transcript_service

logger = logging.getLogger(__name__)

# ``count_tokens`` is the canonical tokenizer, defined once in
# app.agent_runtime.context_manager and re-exported here (imported above)
# under its historical name so existing callers stay unchanged.


# ── Token budget ─────────────────────────────────────────────────────────
# Designed for 1M-context models (DeepSeek V4 / Mimo).

class TokenBudget:
    MODEL_CONTEXT_WINDOW = 1_000_000
    COMPRESS_THRESHOLD_RATIO = 0.75

    SYSTEM_PROMPT_BUDGET = 3_000
    DEBRIEF_REFERENCE_BUDGET = 2_000
    MEMORY_BUDGET = 6_000
    RETRIEVED_CONTEXT_BUDGET = 8_000
    SESSION_STATE_BUDGET = 3_000
    RECENT_TURNS_BUDGET = 32_000
    CURRENT_INPUT_BUDGET = 4_000

    COMPRESS_PROTECT_FIRST_N = 3
    COMPRESS_PROTECT_LAST_N = 6


# ── AssembledContext dataclass ───────────────────────────────────────────


@dataclass
class AssembledContext:
    """All the slot contents for one chat / agent turn.

    Field names match the keys in :data:`SLOT_ORDER`. Anything not
    populated defaults to empty and gets skipped at render time.
    """

    # System prompt slot is rendered as a bare prefix (no [Tag]
    # header) because the LLM treats it as the system prompt.
    system_prompt: str = ""

    # [Record Context] — interview reference for debrief sessions.
    debrief_reference: str = ""

    # [Context Summary] — compaction summary carried across turns
    # (sourced from the session's ``summary`` column). Semi-stable: only
    # changes when a compaction fires, so it sits in the cache-stable prefix.
    summary: str = ""

    # [Memory] — v3 memory bundle (user_profile first, then index /
    # descriptions / active bodies, in the order V3MemoryContext.render
    # produces).
    memory_block: str = ""

    # [Retrieved Context] — RAG knowledge chunks only.
    retrieved_context: str = ""

    # [Recent Turns] — list of {seq, role, content} message dicts.
    recent_turns: list[dict] = field(default_factory=list)

    # [Current Query] — the user's (rewritten) standalone question.
    current_input: str = ""

    # Computed at the end of _assemble for telemetry / token-budget logging.
    context_text: str = ""
    total_tokens: int = 0


# ── Single source of slot ordering ────────────────────────────────────────
# Tuples: (field_name on AssembledContext, slot tag, custom renderer).
# Renderer is ``None`` for plain-string fields (rendered verbatim).
# Adding a new slot = one entry here + matching dataclass field.

_SlotRenderer = Callable[[AssembledContext], str] | None


def _render_recent_turns(ctx: AssembledContext) -> str:
    if not ctx.recent_turns:
        return ""
    return "\n".join(f"{m['role']}: {m['content']}" for m in ctx.recent_turns)


SLOT_ORDER: list[tuple[str, str | None, _SlotRenderer]] = [
    # field_name,              tag (None = no header),    custom renderer
    # Cache-stable prefix first (system / record / summary / recent turns),
    # then the per-turn-variable grounding (memory + RAG), then the query —
    # so a per-turn grounding change can't invalidate the cached prefix.
    ("system_prompt",           None,                      None),
    ("debrief_reference",      "[Record Context]",        None),
    ("summary",                "[Context Summary]",       None),
    ("recent_turns",           "[Recent Turns]",          _render_recent_turns),
    ("memory_block",           "[Memory]",                None),
    ("retrieved_context",      "[Retrieved Context]",     None),
    ("current_input",          "[Current Query]",         None),
]


# Slots the lightweight rewrite-context renderer skips (system rules
# isn't useful to a query rewriter; the rewriter just needs the recent
# turns + the current message).
_REWRITE_SKIP_FIELDS = {"system_prompt", "memory_block", "retrieved_context"}


# ── Prompt rendering ─────────────────────────────────────────────────────


class PromptRenderer:
    """Renders an :class:`AssembledContext` into a single prompt string.

    Both renderers iterate :data:`SLOT_ORDER`; the rewrite variant
    just filters out a few slots that don't help query rewriting.
    """

    def render_answer_prompt(
        self,
        ctx: AssembledContext,
        *,
        system_prompt: str,
        skip_fields: set[str] | frozenset[str] = frozenset(),
    ) -> str:
        """Render every populated slot in SLOT_ORDER into one prompt string.

        ``skip_fields`` lets a messages-based caller (the L2 agent) omit a slot
        it renders separately — e.g. ``{"current_input"}`` so the query becomes
        a user message instead of trailing the system block.
        """
        ctx.system_prompt = system_prompt.strip()
        return self._render(ctx, skip_fields=set(skip_fields))

    def render_context_text(self, ctx: AssembledContext) -> str:
        """Lightweight rendering for the query-planner / rewriter input.

        Drops system rules + memory + retrieved context — the planner
        doesn't need them to do pronoun resolution. Includes the summary +
        recent turns + current query.
        """
        return self._render(ctx, skip_fields=_REWRITE_SKIP_FIELDS)

    @staticmethod
    def _render(ctx: AssembledContext, *, skip_fields: set[str]) -> str:
        parts: list[str] = []
        for field_name, tag, custom in SLOT_ORDER:
            if field_name in skip_fields:
                continue
            if custom is not None:
                rendered = custom(ctx)
            else:
                rendered = str(getattr(ctx, field_name) or "").strip()
            if not rendered:
                continue
            if tag is None:
                parts.append(rendered)
            else:
                parts.append(f"{tag}\n{rendered}")
        return "\n\n".join(parts)


# ── Trimming utilities ───────────────────────────────────────────────────


def trim_messages(messages: list[dict], budget: int) -> list[dict]:
    """Keep the most recent messages within a token budget."""
    total = 0
    cutoff_index = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        tokens = count_tokens(messages[index]["content"])
        if total + tokens > budget:
            cutoff_index = index + 1
            break
        total += tokens
    else:
        cutoff_index = 0
    return messages[cutoff_index:]


def trim_items(items: list[dict], *, content_key: str, budget: int) -> list[dict]:
    """Keep items in order until the token budget is exhausted."""
    selected: list[dict] = []
    total = 0
    for item in items:
        tokens = count_tokens(str(item.get(content_key) or ""))
        if selected and total + tokens > budget:
            break
        selected.append(item)
        total += tokens
    return selected


# ── Pipeline ─────────────────────────────────────────────────────────────


class ContextAssemblyPipeline:
    DEFAULT_RECENT_TURNS = 20

    def __init__(
        self,
        budget: TokenBudget | None = None,
        renderer: PromptRenderer | None = None,
    ):
        self.budget = budget or TokenBudget()
        self.renderer = renderer or PromptRenderer()

    # ── Public API ────────────────────────────────────────────────────
    # ``assemble_rewrite_context`` was retired with the planner merge
    # — the planner now reads recent_turns directly via
    # ``transcript_service`` instead of going through this pipeline
    # (which was over-fitted to producing pre-rendered prompt strings).

    def assemble_answer_context(
        self,
        session_id: str,
        current_query: str,
        memory_block: str = "",
        debrief_reference: str = "",
        knowledge_chunks: list[dict] | None = None,
    ) -> AssembledContext:
        """Full context for answer generation.

        ``memory_block``        rendered v3 memory bundle (user_profile
                                first, by V3MemoryContext.render's
                                fixed contract)
        ``debrief_reference``   interview reference manifest for debrief
                                sessions. Caller may leave this empty
                                in non-debrief mode and let the
                                pipeline auto-inject when applicable.
        ``knowledge_chunks``    RAG output chunks (already reranked).
        """
        return self._assemble(
            session_id=session_id,
            current_query=current_query,
            memory_block=memory_block,
            debrief_reference=debrief_reference,
            knowledge_chunks=knowledge_chunks or [],
        )

    # ── Internal ──────────────────────────────────────────────────────

    def _assemble(
        self,
        session_id: str,
        current_query: str,
        memory_block: str,
        debrief_reference: str,
        knowledge_chunks: list[dict],
        *,
        skip_debrief_autoinject: bool = False,
    ) -> AssembledContext:
        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            recent_turns: list[dict] = []
        else:
            recent_turns = transcript_service.get_recent_turns(
                session_id=session_id,
                max_turns=self.DEFAULT_RECENT_TURNS,
                after_seq=meta["compaction_cursor"],
            )

        cleaned_turns = self._repair_pairs(
            trim_messages(self._sanitize(recent_turns), self.budget.RECENT_TURNS_BUDGET)
        )

        # Auto-inject the interview reference for debrief sessions when the
        # caller didn't supply one. Mode + interview_id come from their
        # dedicated columns (session_type / interview_id) — the
        # mock_interview_state column plays no part in context assembly.
        # ``skip_debrief_autoinject`` lets the lightweight rewrite path bail
        # out before the SQL round-trip.
        if (
            not skip_debrief_autoinject
            and not debrief_reference
            and meta is not None
        ):
            session_type = meta.get("session_type")
            interview_id = meta.get("interview_id")
            if session_type == "debrief" and interview_id:
                from app.services.chat.interview_reference import build_interview_reference
                ref = build_interview_reference(interview_id, meta["user_id"])
                if ref:
                    debrief_reference = ref
            elif interview_id and session_type != "debrief":
                # Data sanity warning — interview_id set but not a debrief
                # session. Log so an operator can investigate; don't crash.
                logger.warning(
                    "session_type=%r has interview_id=%s but isn't debrief; "
                    "reference slot stays empty",
                    session_type, interview_id,
                )

        # RAG retrieved-context: only knowledge_chunks now. The legacy
        # "memories mixed into retrieved_context" path is gone — memory
        # has its own dedicated slot.
        retrieved_parts: list[str] = []
        if knowledge_chunks:
            trimmed_chunks = trim_items(
                knowledge_chunks,
                content_key="text",
                budget=self.budget.RETRIEVED_CONTEXT_BUDGET,
            )
            for i, chunk in enumerate(trimmed_chunks, 1):
                source = chunk.get("source_type") or chunk.get("source") or "knowledge"
                score = chunk.get("score")
                score_text = f" score={float(score):.3f}" if score is not None else ""
                retrieved_parts.append(
                    f"[K{i}] [{source}{score_text}] {chunk.get('text', '')}"
                )
        retrieved_context = "\n\n".join(retrieved_parts)

        ctx = AssembledContext(
            debrief_reference=debrief_reference,
            summary=str((meta or {}).get("summary") or ""),
            memory_block=memory_block,
            retrieved_context=retrieved_context,
            recent_turns=cleaned_turns,
            current_input=current_query,
        )
        ctx.context_text = self.renderer.render_context_text(ctx)
        ctx.total_tokens = count_tokens(ctx.context_text)
        return ctx

    @staticmethod
    def _sanitize(messages: list[dict]) -> list[dict]:
        sanitized = []
        for message in messages:
            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "").strip()
            if role not in {"User", "Agent"} or not content:
                continue
            if content.startswith("[SYSTEM_") or content.startswith("[DEBUG_"):
                continue
            sanitized.append(
                {
                    "seq": message.get("seq", 0),
                    "role": role,
                    "content": content,
                    # Anthropic-style blocks (text / tool_use / tool_result)
                    # kept so the L2 agent can reconstruct prior tool roundtrips
                    # as real messages. L1 ignores them (renders content text).
                    "blocks": message.get("blocks") or [{"type": "text", "text": content}],
                }
            )
        return sanitized

    @staticmethod
    def _repair_pairs(messages: list[dict]) -> list[dict]:
        repaired = list(messages)
        while repaired and repaired[0]["role"] == "Agent":
            repaired.pop(0)
        while repaired and repaired[-1]["role"] == "User":
            repaired.pop()
        return repaired


context_pipeline = ContextAssemblyPipeline()
prompt_renderer = context_pipeline.renderer


__all__ = [
    "AssembledContext",
    "ContextAssemblyPipeline",
    "PromptRenderer",
    "SLOT_ORDER",
    "TokenBudget",
    "context_pipeline",
    "count_tokens",
    "prompt_renderer",
    "trim_items",
    "trim_messages",
]
