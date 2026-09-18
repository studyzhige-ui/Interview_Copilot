"""Product context selection: Memory, RAG, runtime facts and history replay.

The dispatch context manager owns compaction and durable replacement history.
This stage selects sources; it does not rewrite history or advance cursors.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from app.core.tokens import token_count as count_tokens
from app.core.config import settings
from app.core.context_budget import RequestBudget
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

    def __init__(self, model_context_window: int | None = None):
        if model_context_window:
            self.MODEL_CONTEXT_WINDOW = model_context_window

    SYSTEM_PROMPT_BUDGET = 3_000
    DEBRIEF_REFERENCE_BUDGET = 2_000
    PERSONALIZATION_GUIDANCE_BUDGET = 6_000
    MEMORY_BUDGET = 6_000
    ATTACHMENT_MANIFEST_BUDGET = 1_500
    SOURCE_READ_STATUS_BUDGET = 1_500
    RETRIEVED_CONTEXT_BUDGET = settings.RAG_RETRIEVED_CONTEXT_TOKENS
    PRODUCT_OBJECT_CONTEXT_BUDGET = 6_000
    OUTPUT_TOKEN_RESERVE = settings.RAG_OUTPUT_TOKEN_RESERVE
    SAFETY_MARGIN = settings.RAG_CONTEXT_SAFETY_MARGIN


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

    # [Context Summary] — lossy Conversation projection carried across turns.
    # It is model-visible data, never a system instruction or fact owner.
    summary: str = ""

    # [Memory] — optional canonical low-authority recall. Legacy mixed Memory
    # is never placed here during the Stage 0→2 migration.
    memory_block: str = ""

    # User-confirmed collaboration guidance read directly from its three real
    # owners (global preference, bound InterviewRecord, Conversation). It is
    # user-specific and therefore never part of the stable system prefix.
    personalization_guidance: str = ""

    # [Retrieved Context] — RAG knowledge chunks only.
    retrieved_context: str = ""

    # [Attachments] — small trusted manifest of server-resolved file ids.
    # File bodies remain untrusted evidence inside [Retrieved Context].
    attachment_manifest: str = ""

    # [Source Read Status] — bounded deterministic status for shared owner
    # reads. The successful bodies themselves remain untrusted evidence in
    # [Retrieved Context]; failures never become citable source chunks.
    source_read_status: str = ""

    # [Referenced Product Objects] — execution-time reread of identities the
    # user explicitly attached to this Turn. It remains low-authority data.
    product_object_context: str = ""

    # [Recent Turns] — list of {seq, role, content} message dicts.
    recent_turns: list[dict] = field(default_factory=list)

    # [Current Query] — the user's original admitted question.
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
    context_report: dict = field(default_factory=dict)
    conversation_id: str = ""
    summary_cursor: int = 0
    window_messages: list[dict] | None = None
    checkpoint_version: int = 0
    through_seq: int = 0
    turn_id: str | None = None
    dispatch_generation: int = 0


class CurrentInputTooLargeError(ValueError):
    """The admitted user input cannot fit without semantic truncation."""

    def __init__(self, *, input_tokens: int, prompt_limit: int):
        self.input_tokens = input_tokens
        self.prompt_limit = prompt_limit
        super().__init__(
            "admitted current input exceeds the active model context window "
            f"({input_tokens} > {prompt_limit} prompt tokens)"
        )


# ── Single source of slot ordering ────────────────────────────────────────
# Tuples: (field_name on AssembledContext, slot tag, custom renderer).
# Renderer is ``None`` for plain-string fields (rendered verbatim).
# Adding a new slot = one entry here + matching dataclass field.

_SlotRenderer = Callable[[AssembledContext], str] | None


def _render_recent_turns(ctx: AssembledContext) -> str:
    if not ctx.recent_turns:
        return ""
    return "\n".join(
        f"{message['role']}: "
        + (
            render_historical_user_content(message)
            if message["role"] == "User"
            else message["content"]
        )
        for message in ctx.recent_turns
    )


def render_historical_user_content(message: dict) -> str:
    """Preserve exact past reference identities without replaying stale facts."""

    references = [
        {
            "kind": str(block.get("kind") or ""),
            "object_id": str(block.get("object_id") or ""),
            "label_at_admission": str(block.get("label") or ""),
        }
        for block in (message.get("blocks") or [])
        if block.get("type") == "product_object_reference"
        and block.get("kind")
        and block.get("object_id")
    ]
    content = str(message.get("content") or "")
    if not references:
        return content
    return (
        "[Historical Explicit Object Identities]\n"
        "These identities record what the user attached to that past Turn. "
        "Labels are historical display snapshots; reread the owner before "
        "using any current business fact.\n"
        + json.dumps(references, ensure_ascii=False, sort_keys=True)
        + "\n\n"
        + content
    )


SLOT_ORDER: list[tuple[str, str | None, _SlotRenderer]] = [
    # field_name,              tag (None = no header),    custom renderer
    # This order is the provider-neutral semantic rendering used by callers
    # that still accept one string. Message-based callers keep system rules,
    # conversation projection/history, and current data in separate payloads.
    ("system_prompt", None, None),
    ("debrief_reference", "[Record Context]", None),
    ("summary", "[Context Summary]", None),
    ("recent_turns", "[Recent Turns]", _render_recent_turns),
    ("personalization_guidance", "[Explicit Guidance]", None),
    ("memory_block", "[Memory]", None),
    ("attachment_manifest", "[Attachments]", None),
    ("source_read_status", "[Source Read Status]", None),
    ("retrieved_context", "[Retrieved Context]", None),
    ("product_object_context", "[Referenced Product Objects]", None),
    ("current_input", "[Current Query]", None),
]


# Slots the lightweight rewrite-context renderer skips (system rules
# isn't useful to a query rewriter; the rewriter just needs the recent
# turns + the current message).
_REWRITE_SKIP_FIELDS = {
    "system_prompt",
    "personalization_guidance",
    "memory_block",
    "attachment_manifest",
    "source_read_status",
    "retrieved_context",
}


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
            from app.services.personalization_service import (
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
