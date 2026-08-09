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
  4. [Recent Turns]        ALL user↔agent dialogue pairs after the compaction
                           cursor (incremental-append, no fixed window).
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

Compaction is triggered at assembly time when total context tokens exceed
``MODEL_CONTEXT_WINDOW * COMPRESS_THRESHOLD_RATIO``. This matches the
Claude Code model: full history in context, compress only at threshold.

This module is distinct from
``app.agent_runtime.context_compactor.QueryLoopCompactor``, which
compresses the running message list inside a single L2 agent
execution (different problem, different file).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from app.core.tokens import token_count as count_tokens
from app.core.tokens import truncate_to_tokens
from app.core.config import settings
from app.rag.domain.models import GroundingBundle, RetrievalResult
from app.rag.grounding.builder import grounding_builder
from app.services.chat.chat_history_service import transcript_service

logger = logging.getLogger(__name__)

# ``count_tokens`` is the canonical tokenizer defined in app.core.tokens.


# ── Token budget ─────────────────────────────────────────────────────────
# Designed for 1M-context models (DeepSeek V4 / Mimo).


class TokenBudget:
    # Default window is a safe LOWER bound fallback; the engine passes the
    # active primary profile's real context_window per turn (AGT-6 — the
    # old hardcoded 1M meant a 128K model NEVER triggered L1 compression
    # and eventually 400'd on an overlong prompt).
    MODEL_CONTEXT_WINDOW = 128_000
    COMPRESS_THRESHOLD_RATIO = 0.75

    def __init__(self, model_context_window: int | None = None):
        if model_context_window:
            self.MODEL_CONTEXT_WINDOW = model_context_window

    SYSTEM_PROMPT_BUDGET = 3_000
    DEBRIEF_REFERENCE_BUDGET = 2_000
    MEMORY_BUDGET = 6_000
    RETRIEVED_CONTEXT_BUDGET = settings.RAG_RETRIEVED_CONTEXT_TOKENS
    CURRENT_INPUT_BUDGET = 4_000
    OUTPUT_TOKEN_RESERVE = settings.RAG_OUTPUT_TOKEN_RESERVE
    SAFETY_MARGIN = settings.RAG_CONTEXT_SAFETY_MARGIN

    COMPRESS_PROTECT_FIRST_N = 3
    COMPRESS_PROTECT_LAST_N = 4


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

    # Final citation sources, aligned 1:1 with the [K#] refs inside
    # ``retrieved_context``. Built HERE (the sole [K#] owner) over the
    # budget-trimmed chunks, so a ref can never point at a chunk that
    # didn't make the cut (retrieval plan §2.7). Empty for non-RAG turns.
    sources: list[dict] = field(default_factory=list)
    grounding: GroundingBundle = field(default_factory=GroundingBundle)
    retrieval_result: RetrievalResult | None = None

    # Computed at the end of _assemble for telemetry / token-budget logging.
    context_text: str = ""
    total_tokens: int = 0
    model_context_window: int = TokenBudget.MODEL_CONTEXT_WINDOW
    prompt_token_limit: int = 0
    output_token_reserve: int = TokenBudget.OUTPUT_TOKEN_RESERVE


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
    ("system_prompt", None, None),
    ("debrief_reference", "[Record Context]", None),
    ("summary", "[Context Summary]", None),
    ("recent_turns", "[Recent Turns]", _render_recent_turns),
    ("memory_block", "[Memory]", None),
    ("retrieved_context", "[Retrieved Context]", None),
    ("current_input", "[Current Query]", None),
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
        skipped = set(skip_fields)
        prompt = self._render(ctx, skip_fields=skipped)
        limit = int(ctx.prompt_token_limit or 0)
        if not limit or count_tokens(prompt) <= limit:
            ctx.total_tokens = count_tokens(prompt)
            return prompt

        # The real system prompt is known only at render time. Reconcile any
        # difference from the assembly-time reserve using a deterministic slot
        # priority; system rules and current input are never truncated.
        over = count_tokens(prompt) - limit
        if ctx.retrieval_result is not None and ctx.grounding.token_count:
            grounding = grounding_builder.build(
                ctx.retrieval_result,
                token_budget=max(0, ctx.grounding.token_count - over - 32),
            )
            ctx.grounding = grounding
            ctx.retrieved_context = grounding.context_text
            ctx.sources = grounding.sources
            prompt = self._render(ctx, skip_fields=skipped)

        for field_name in ("memory_block", "debrief_reference", "summary"):
            current = str(getattr(ctx, field_name) or "")
            while current and count_tokens(prompt) > limit:
                excess = count_tokens(prompt) - limit
                current = truncate_to_tokens(
                    current, max(0, count_tokens(current) - excess - 16)
                )
                setattr(ctx, field_name, current)
                prompt = self._render(ctx, skip_fields=skipped)

        while ctx.recent_turns and count_tokens(prompt) > limit:
            ctx.recent_turns = (
                ctx.recent_turns[2:] if len(ctx.recent_turns) >= 2 else []
            )
            prompt = self._render(ctx, skip_fields=skipped)
        if count_tokens(prompt) > limit:
            raise ValueError("final prompt exceeds the model context budget")
        ctx.total_tokens = count_tokens(prompt)
        return prompt

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


# ── Pipeline ─────────────────────────────────────────────────────────────


def _turn_tokens(m: dict) -> int:
    """Token weight of one persisted turn for the compression threshold.

    Agent turns carry most of their volume in content BLOCKS (tool_use /
    tool_result), not ``content`` — counting content alone systematically
    underestimated agent sessions and pushed the whole compression job onto
    the in-turn compactor every turn (AGT-7). Blocks are only counted when
    they are richer than the read-time synthesized single text block
    (which just mirrors content).
    """
    base = count_tokens(m.get("content") or "")
    blocks = m.get("blocks")
    if blocks and (len(blocks) > 1 or (blocks[0] or {}).get("type") != "text"):
        base += count_tokens(json.dumps(blocks, ensure_ascii=False))
    return base


class ContextAssemblyPipeline:
    def __init__(
        self,
        budget: TokenBudget | None = None,
        renderer: PromptRenderer | None = None,
    ):
        self.budget = budget or TokenBudget()
        self.renderer = renderer or PromptRenderer()

    # ── Public API ────────────────────────────────────────────────────

    async def assemble_answer_context(
        self,
        session_id: str,
        current_query: str,
        memory_block: str = "",
        debrief_reference: str = "",
        retrieval_result: RetrievalResult | None = None,
        user_id: str | None = None,
        model_context_window: int | None = None,
    ) -> AssembledContext:
        """Full context for answer generation.

        ``memory_block``        rendered v3 memory bundle (user_profile
                                first, by V3MemoryContext.render's
                                fixed contract)
        ``debrief_reference``   interview reference manifest for debrief
                                sessions. Caller may leave this empty
                                in non-debrief mode and let the
                                pipeline auto-inject when applicable.
        ``retrieval_result``    canonical RAG result with intent provenance.
        ``user_id``             the OWNER's username principal — drives the
                                compaction summarizer's LLM resolution.
                                (NOT ``meta["user_id"]``, which is the
                                integer users.id pk.)
        """
        return await self._assemble(
            session_id=session_id,
            current_query=current_query,
            memory_block=memory_block,
            debrief_reference=debrief_reference,
            retrieval_result=retrieval_result,
            user_id=user_id,
            model_context_window=model_context_window,
        )

    # ── Internal ──────────────────────────────────────────────────────

    async def _assemble(
        self,
        session_id: str,
        current_query: str,
        memory_block: str,
        debrief_reference: str,
        retrieval_result: RetrievalResult | None,
        *,
        skip_debrief_autoinject: bool = False,
        user_id: str | None = None,
        model_context_window: int | None = None,
    ) -> AssembledContext:
        meta = await asyncio.to_thread(
            transcript_service.get_session_meta,
            session_id,
        )
        if meta is None:
            all_turns: list[dict] = []
        else:
            all_turns = await asyncio.to_thread(
                transcript_service.get_turns_after,
                session_id,
                after_seq=meta["compaction_cursor"],
            )

        cleaned_turns = self._repair_pairs(self._sanitize(all_turns))

        # Auto-inject the interview reference before budgeting. The old order
        # performed the context-window check first and therefore never counted
        # this potentially large slot.
        # caller didn't supply one. type + the bound record come from their
        # dedicated columns (type / subject_type / subject_id).
        # ``skip_debrief_autoinject`` lets the lightweight rewrite path bail
        # out before the SQL round-trip.
        if not skip_debrief_autoinject and not debrief_reference and meta is not None:
            conv_type = meta.get("type")
            record_id = (
                meta.get("subject_id")
                if meta.get("subject_type") == "interview_record"
                else None
            )
            if conv_type == "debrief" and record_id:
                from app.services.chat.interview_reference import (
                    build_interview_reference,
                )

                ref = build_interview_reference(record_id, meta["user_id"])
                if ref:
                    debrief_reference = ref
            elif record_id and conv_type != "debrief":
                logger.warning(
                    "type=%r has subject_id=%s but isn't debrief; "
                    "reference slot stays empty",
                    conv_type,
                    record_id,
                )

        window = model_context_window or self.budget.MODEL_CONTEXT_WINDOW
        output_reserve = min(self.budget.OUTPUT_TOKEN_RESERVE, max(128, window // 4))
        safety_margin = min(self.budget.SAFETY_MARGIN, max(0, window // 10))
        prompt_limit = max(1, window - output_reserve - safety_margin)
        system_reserve = min(
            self.budget.SYSTEM_PROMPT_BUDGET, max(1, prompt_limit // 4)
        )

        # Per-slot limits are executable policy, not documentation constants.
        current_query = truncate_to_tokens(
            current_query, self.budget.CURRENT_INPUT_BUDGET
        )
        memory_block = truncate_to_tokens(memory_block, self.budget.MEMORY_BUDGET)
        debrief_reference = truncate_to_tokens(
            debrief_reference, self.budget.DEBRIEF_REFERENCE_BUDGET
        )
        old_summary = str((meta or {}).get("summary") or "")

        effective_result = retrieval_result or RetrievalResult()
        desired_grounding = min(
            self.budget.RETRIEVED_CONTEXT_BUDGET,
            sum(
                count_tokens(str(chunk.get("text") or ""))
                for chunk in effective_result.chunks
            ),
        )
        turns_tokens = sum(_turn_tokens(message) for message in cleaned_turns)
        overhead_tokens = (
            system_reserve
            + count_tokens(old_summary)
            + count_tokens(memory_block)
            + count_tokens(current_query)
            + count_tokens(debrief_reference)
            + desired_grounding
        )
        compress_threshold = min(
            int(window * self.budget.COMPRESS_THRESHOLD_RATIO),
            prompt_limit,
        )
        if (
            turns_tokens + overhead_tokens > compress_threshold
            and len(cleaned_turns) > self.budget.COMPRESS_PROTECT_LAST_N
        ):
            cleaned_turns, old_summary = await self._maybe_compact(
                session_id=session_id,
                user_id=user_id,
                meta=meta,
                cleaned_turns=cleaned_turns,
                old_summary=old_summary,
                compress_threshold=compress_threshold,
                overhead_tokens=overhead_tokens,
            )

        # If the protected tail itself is too large, remove complete oldest
        # pairs. Current input is a separate protected slot and is never lost.
        def fixed_tokens() -> int:
            return (
                system_reserve
                + count_tokens(old_summary)
                + count_tokens(memory_block)
                + count_tokens(current_query)
                + count_tokens(debrief_reference)
                + sum(_turn_tokens(message) for message in cleaned_turns)
            )

        while cleaned_turns and fixed_tokens() > prompt_limit:
            cleaned_turns = cleaned_turns[2:] if len(cleaned_turns) >= 2 else []

        remaining = max(0, prompt_limit - fixed_tokens())
        grounding = grounding_builder.build(
            effective_result,
            token_budget=min(self.budget.RETRIEVED_CONTEXT_BUDGET, remaining),
        )

        ctx = AssembledContext(
            debrief_reference=debrief_reference,
            summary=old_summary,
            memory_block=memory_block,
            retrieved_context=grounding.context_text,
            recent_turns=cleaned_turns,
            current_input=current_query,
            sources=grounding.sources,
            grounding=grounding,
            retrieval_result=effective_result,
            model_context_window=window,
            prompt_token_limit=prompt_limit,
            output_token_reserve=output_reserve,
        )
        ctx.context_text = self.renderer.render_context_text(ctx)
        ctx.total_tokens = count_tokens(
            self.renderer._render(ctx, skip_fields={"system_prompt"})
        )
        return ctx

    # ── Assembly-time compaction ──────────────────────────────────────

    async def _maybe_compact(
        self,
        *,
        session_id: str,
        user_id: str | None = None,
        meta: dict,
        cleaned_turns: list[dict],
        old_summary: str,
        compress_threshold: int,
        overhead_tokens: int,
    ) -> tuple[list[dict], str]:
        """Compress old turns when the assembled context exceeds the threshold.

        Protects the last ``COMPRESS_PROTECT_LAST_N`` messages (verbatim).
        Everything before that is summarized into the session's ``summary``
        column and the ``compaction_cursor`` is advanced.

        Returns ``(remaining_turns, new_summary)``.
        """
        protect_n = self.budget.COMPRESS_PROTECT_LAST_N
        to_compress = cleaned_turns[:-protect_n]
        to_keep = cleaned_turns[-protect_n:]

        if not to_compress:
            return cleaned_turns, old_summary

        conversation = "\n".join(f"{m['role']}: {m['content']}" for m in to_compress)

        from app.services.chat.conversation_summarizer import summarize_conversation

        # NB: meta["user_id"] is the integer pk — the summarizer needs the
        # username principal, threaded from the engine (dual-review fix).
        new_summary = await summarize_conversation(
            old_summary,
            conversation,
            user_id=user_id,
        )
        if not new_summary:
            return cleaned_turns, old_summary

        new_cursor = to_compress[-1]["seq"]

        await asyncio.to_thread(
            transcript_service.update_session_fields,
            session_id,
            summary=new_summary,
            compaction_cursor=new_cursor,
        )
        logger.info(
            "Assembly-time compaction for session %s: compressed %d messages, "
            "cursor advanced to seq %d, summary=%d tokens",
            session_id,
            len(to_compress),
            new_cursor,
            count_tokens(new_summary),
        )

        return to_keep, new_summary

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
                    "blocks": message.get("blocks")
                    or [{"type": "text", "text": content}],
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
]
