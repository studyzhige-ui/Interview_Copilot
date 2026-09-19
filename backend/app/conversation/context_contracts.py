"""Typed context data and ordering, independent of assembly and transport."""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Callable, Protocol
from app.core.config import settings
from app.rag.domain.models import GroundingBundle, RetrievalResult


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


_REWRITE_SKIP_FIELDS = {
    "system_prompt",
    "personalization_guidance",
    "memory_block",
    "attachment_manifest",
    "source_read_status",
    "retrieved_context",
}


class ContextRenderer(Protocol):
    def render_stable_system_prompt(
        self, ctx: AssembledContext, *, system_prompt: str
    ) -> str: ...
