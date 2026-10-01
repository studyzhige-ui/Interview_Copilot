"""Product context selection: Memory, RAG, runtime facts and history replay.

The dispatch context manager owns compaction and durable replacement history.
This stage selects sources; it does not rewrite history or advance cursors.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.tokens import token_count as count_tokens
from app.conversation.context_contracts import (
    TokenBudget,
    AssembledContext,
    CurrentInputTooLargeError,
    SLOT_ORDER,
    _REWRITE_SKIP_FIELDS,
    render_historical_user_content,
)
from app.core.context_budget import RequestBudget
from app.rag.domain.models import RetrievalResult
from app.rag.grounding.builder import grounding_builder
from app.conversation.application.chat_history_service import transcript_service

logger = logging.getLogger(__name__)

# ``count_tokens`` is the canonical tokenizer defined in app.core.tokens.


# ── Token budget ─────────────────────────────────────────────────────────
# Designed for 1M-context models (DeepSeek V4 / Mimo).


# ── AssembledContext dataclass ───────────────────────────────────────────


# ── Single source of slot ordering ────────────────────────────────────────
# Tuples: (field_name on AssembledContext, slot tag, custom renderer).
# Renderer is ``None`` for plain-string fields (rendered verbatim).
# Adding a new slot = one entry here + matching dataclass field.


# Slots the lightweight rewrite-context renderer skips (system rules
# isn't useful to a query rewriter; the rewriter just needs the recent
# turns + the current message).


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
        if ctx.prompt_token_limit:
            from app.conversation.provider_context import compose_provider_context

            compose_provider_context(ctx, renderer=self, system_prompt=system_prompt)
            prompt = self._render(ctx, skip_fields=skipped)
        else:
            ctx.total_tokens = count_tokens(prompt)
        return prompt

    def render_context_text(self, ctx: AssembledContext) -> str:
        """Lightweight rendering for the query-planner / rewriter input.

        Drops system rules + memory + retrieved context — the planner
        doesn't need them to do pronoun resolution. Includes the summary +
        recent turns + current query.
        """
        return self._render(ctx, skip_fields=_REWRITE_SKIP_FIELDS)

    def render_stable_system_prompt(
        self,
        ctx: AssembledContext,
        *,
        system_prompt: str,
    ) -> str:
        """Render only stable instructions.

        Profile/record data and the compaction summary are user-specific model
        context and must not gain system authority or enter a cross-user cache
        prefix.
        """
        ctx.system_prompt = system_prompt.strip()
        return self._render(
            ctx,
            skip_fields={
                "debrief_reference",
                "summary",
                "recent_turns",
                "personalization_guidance",
                "memory_block",
                "attachment_manifest",
                "source_read_status",
                "retrieved_context",
                "product_object_context",
                "current_input",
            },
        )

    def render_current_user_message(self, ctx: AssembledContext) -> str:
        """Render typed per-turn context immediately beside the user input."""
        return self._render(
            ctx,
            skip_fields={
                "system_prompt",
                "summary",
                "recent_turns",
            },
        )

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
        attachment_manifest: str = "",
        source_read_status: str = "",
        product_object_context: str = "",
        retrieval_result: RetrievalResult | None = None,
        user_id: str | None = None,
        model_context_window: int | None = None,
        model_output_tokens: int | None = None,
    ) -> AssembledContext:
        """Full context for answer generation.

        ``memory_block``        optional canonical low-authority recall
        ``debrief_reference``   interview reference manifest for debrief
                                sessions. Caller may leave this empty
                                in non-debrief mode and let the
                                pipeline auto-inject when applicable.
        ``source_read_status``  bounded success/failure facts for the current
                                shared read-only source acquisition.
        ``retrieval_result``    canonical RAG result with intent provenance.
        ``user_id``             OWNER's username principal; background
                                compaction uses the selected answer model at dispatch.
        """
        return await self._assemble(
            session_id=session_id,
            current_query=current_query,
            memory_block=memory_block,
            debrief_reference=debrief_reference,
            attachment_manifest=attachment_manifest,
            source_read_status=source_read_status,
            product_object_context=product_object_context,
            retrieval_result=retrieval_result,
            user_id=user_id,
            model_context_window=model_context_window,
            model_output_tokens=model_output_tokens,
        )

    # ── Internal ──────────────────────────────────────────────────────

    async def _assemble(
        self,
        session_id: str,
        current_query: str,
        memory_block: str,
        debrief_reference: str,
        attachment_manifest: str,
        source_read_status: str,
        product_object_context: str,
        retrieval_result: RetrievalResult | None,
        *,
        skip_debrief_autoinject: bool = False,
        user_id: str | None = None,
        model_context_window: int | None = None,
        model_output_tokens: int | None = None,
    ) -> AssembledContext:
        meta = await asyncio.to_thread(
            transcript_service.get_session_meta,
            session_id,
        )
        if meta is None:
            all_turns: list[dict] = []
            checkpoint = None
        else:
            from app.conversation.context_store import load

            checkpoint = await asyncio.to_thread(load, session_id)
            all_turns = await asyncio.to_thread(
                transcript_service.get_turns_after,
                session_id,
                after_seq=(checkpoint or {}).get("through_seq", 0),
            )

        cleaned_turns = self._repair_pairs(self._sanitize(all_turns))

        personalization_guidance = ""
        if meta is not None and isinstance(meta.get("user_id"), int):
            from app.career.application.personalization import (
                resolve_guidance_projection,
            )

            personalization_guidance = await asyncio.to_thread(
                resolve_guidance_projection,
                conversation_id=session_id,
                user_pk=meta["user_id"],
            )

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
                from app.conversation.application.interview_reference import (
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
        if model_output_tokens:
            output_reserve = min(output_reserve, model_output_tokens)
        request_budget = RequestBudget.resolve(
            window, output_reserve, self.budget.SAFETY_MARGIN
        )
        prompt_limit = request_budget.input_limit
        system_reserve = min(
            self.budget.SYSTEM_PROMPT_BUDGET, max(1, prompt_limit // 4)
        )

        # The admitted original input owns this Turn's direction.  It is never
        # silently truncated to make room for optional history or retrieval.
        # If the input itself cannot fit, fail explicitly so the user can split
        # it or attach it as a source without changing its meaning.
        current_input_tokens = count_tokens(current_query)
        if current_input_tokens + system_reserve > prompt_limit:
            raise CurrentInputTooLargeError(
                input_tokens=current_input_tokens,
                prompt_limit=max(0, prompt_limit - system_reserve),
            )
        # Optional recall must remain a complete evidence envelope with intact
        # citation identities, never a token slice of JSON/Markdown.
        assembly_omissions: list[str] = []
        if count_tokens(memory_block) > self.budget.MEMORY_BUDGET:
            memory_block = ""
            assembly_omissions.append("memory_block")
        # Explicit guidance and server-resolved identity/status envelopes are
        # mandatory whole records. The final compiler either admits them or
        # reports capacity failure; slicing them would corrupt their contract.
        if count_tokens(debrief_reference) > self.budget.DEBRIEF_REFERENCE_BUDGET:
            debrief_reference = ""
            assembly_omissions.append("debrief_reference")
        # Bootstrap from the original transcript, including histories previously
        # hidden behind the legacy cursor. Never promote an old lossy summary.
        from app.conversation.provider_context import reconstruct_history_messages
        from app.conversation.context_window import admit

        window_messages = admit(
            [
                *((checkpoint or {}).get("state", {}).get("messages", [])),
                *reconstruct_history_messages(cleaned_turns),
            ]
        )
        old_summary = ""
        summary_cursor = 0
        compaction_trace: dict = {"status": "deferred_to_dispatch"}

        effective_result = retrieval_result or RetrievalResult()
        turns_tokens = count_tokens(json.dumps(window_messages, ensure_ascii=False))

        # History is only removed after a successful durable summary. A failed
        # summary must not silently turn into an unrelated short conversation.
        def fixed_tokens() -> int:
            return (
                system_reserve
                + count_tokens(old_summary)
                + count_tokens(memory_block)
                + count_tokens(personalization_guidance)
                + count_tokens(current_query)
                + count_tokens(debrief_reference)
                + count_tokens(attachment_manifest)
                + count_tokens(source_read_status)
                + count_tokens(product_object_context)
                + turns_tokens
            )

        remaining = max(0, prompt_limit - (fixed_tokens() - turns_tokens))
        grounding = grounding_builder.build(
            effective_result,
            token_budget=min(self.budget.RETRIEVED_CONTEXT_BUDGET, remaining),
        )

        ctx = AssembledContext(
            debrief_reference=debrief_reference,
            summary=old_summary,
            memory_block=memory_block,
            personalization_guidance=personalization_guidance,
            attachment_manifest=attachment_manifest,
            source_read_status=source_read_status,
            product_object_context=product_object_context,
            retrieved_context=grounding.context_text,
            recent_turns=cleaned_turns,
            current_input=current_query,
            sources=grounding.sources,
            grounding=grounding,
            retrieval_result=effective_result,
            model_context_window=window,
            prompt_token_limit=prompt_limit,
            output_token_reserve=output_reserve,
            conversation_id=session_id,
            summary_cursor=summary_cursor,
            window_messages=window_messages,
            checkpoint_version=(checkpoint or {}).get("version", 0),
            through_seq=max(
                [m["seq"] for m in cleaned_turns],
                default=(checkpoint or {}).get("through_seq", 0),
            ),
            context_report={
                "compaction": compaction_trace,
                "omitted": assembly_omissions,
            },
        )
        ctx.context_text = self.renderer.render_context_text(ctx)
        ctx.total_tokens = count_tokens(
            self.renderer._render(ctx, skip_fields={"system_prompt"})
        )
        return ctx

    @staticmethod
    def _sanitize(messages: list[dict]) -> list[dict]:
        sanitized = []
        for position, message in enumerate(messages):
            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "").strip()
            if role not in {"User", "Agent"} or not content:
                continue
            if content.startswith("[SYSTEM_") or content.startswith("[DEBUG_"):
                continue
            try:
                seq = int(message.get("seq", 0) or 0)
            except (TypeError, ValueError):
                seq = 0
            sanitized.append(
                {
                    "seq": seq,
                    "_position": position,
                    "role": role,
                    "content": content,
                    # Anthropic-style blocks (text / tool_use / tool_result)
                    # kept so the L2 agent can reconstruct prior tool roundtrips
                    # as real messages. L1 ignores them (renders content text).
                    "blocks": message.get("blocks")
                    or [{"type": "text", "text": content}],
                }
            )
        sanitized.sort(key=lambda item: (item["seq"], item["_position"]))
        for item in sanitized:
            item.pop("_position", None)
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
    "render_historical_user_content",
]
