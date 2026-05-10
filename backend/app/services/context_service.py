"""Context assembly pipeline — 6-slot context window for all session modes.

Slots:
  1. system_prompt        — role identity + user_profile + mode-specific hints
  2. reference_material   — analysis summary (debrief) / interview plan (mock)
  3. retrieved_context     — vector search results (transcript, resume, knowledge)
  4. session_state         — conversation summary (compressed periodically)
  5. recent_turns          — last N turns of raw dialogue
  6. current_input         — user's current message
"""

import json
import logging
from dataclasses import dataclass, field

import tiktoken

from app.services.state_utils import (
    default_session_state_for_type,
    parse_session_state,
)
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

try:
    _tokenizer = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    _tokenizer = None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _tokenizer is None:
        return len(text.encode("utf-8")) // 3
    return len(_tokenizer.encode(text))


# ── Token budget ─────────────────────────────────────────────────────────
# Designed for 1M context models (DeepSeek V4 / Mimo).
# Compression triggers at 75% of context window (hermes pattern).

class TokenBudget:
    MODEL_CONTEXT_WINDOW = 1_000_000
    COMPRESS_THRESHOLD_RATIO = 0.75

    SYSTEM_PROMPT_BUDGET = 3_000
    REFERENCE_MATERIAL_BUDGET = 2_000
    RETRIEVED_CONTEXT_BUDGET = 8_000
    SESSION_STATE_BUDGET = 2_000
    RECENT_TURNS_BUDGET = 32_000
    CURRENT_INPUT_BUDGET = 4_000

    COMPRESS_PROTECT_FIRST_N = 3
    COMPRESS_PROTECT_LAST_N = 6
    COMPACT_EVERY_N_TURNS = 20


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class AssembledContext:
    system_prompt: str = ""
    user_profile: list[dict] = field(default_factory=list)
    reference_material: str = ""
    retrieved_context: str = ""
    session_state: dict = field(default_factory=dict)
    recent_turns: list[dict] = field(default_factory=list)
    current_input: str = ""
    context_text: str = ""
    total_tokens: int = 0


# ── Prompt rendering ─────────────────────────────────────────────────────

class PromptRenderer:
    def render_answer_prompt(
        self,
        ctx: AssembledContext,
        *,
        system_rules: str,
    ) -> str:
        parts = [system_rules.strip()]
        profile_text = self._render_user_profile(ctx.user_profile)
        if profile_text:
            parts.append(f"[User Profile]\n{profile_text}")
        if ctx.reference_material:
            parts.append(f"[Reference Material]\n{ctx.reference_material}")
        if ctx.retrieved_context:
            parts.append(f"[Retrieved Context]\n{ctx.retrieved_context}")
        state_text = self._render_state(ctx.session_state)
        if state_text:
            parts.append(f"[Session State]\n{state_text}")
        if ctx.recent_turns:
            parts.append(f"[Recent Turns]\n{self._render_turns(ctx.recent_turns)}")
        parts.append(f"[Current Query]\n{ctx.current_input.strip()}")
        return "\n\n".join(part for part in parts if part.strip())

    def render_context_text(self, ctx: AssembledContext) -> str:
        parts = []
        if ctx.reference_material:
            parts.append(f"[Reference Material]\n{ctx.reference_material}")
        if ctx.retrieved_context:
            parts.append(f"[Retrieved Context]\n{ctx.retrieved_context}")
        state_text = self._render_state(ctx.session_state)
        if state_text:
            parts.append(f"[Session State]\n{state_text}")
        if ctx.recent_turns:
            parts.append(f"[Recent Turns]\n{self._render_turns(ctx.recent_turns)}")
        parts.append(f"[Current Query]\n{ctx.current_input.strip()}")
        return "\n\n".join(part for part in parts if part.strip())

    @staticmethod
    def _render_state(state: dict) -> str:
        if not state:
            return ""
        return json.dumps(state, ensure_ascii=False, indent=2)

    @staticmethod
    def _render_turns(turns: list[dict]) -> str:
        return "\n".join(f"{item['role']}: {item['content']}" for item in turns)

    @staticmethod
    def _render_user_profile(profile_items: list[dict]) -> str:
        if not profile_items:
            return ""
        return "\n".join(
            f"- {item.get('description', '')}: {item.get('content', '')}"
            for item in profile_items
        )


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

    def assemble_rewrite_context(
        self,
        session_id: str,
        current_query: str,
    ) -> AssembledContext:
        """Lightweight context for query rewriting (no memories/knowledge)."""
        return self._assemble(
            session_id=session_id,
            current_query=current_query,
            relevant_memories=[],
            knowledge_chunks=[],
            reference_material="",
        )

    def assemble_answer_context(
        self,
        session_id: str,
        current_query: str,
        user_profile: list[dict] | None = None,
        relevant_memories: list[dict] | None = None,
        knowledge_chunks: list[dict] | None = None,
        reference_material: str = "",
    ) -> AssembledContext:
        """Full context for answer generation."""
        return self._assemble(
            session_id=session_id,
            current_query=current_query,
            user_profile=user_profile or [],
            relevant_memories=relevant_memories or [],
            knowledge_chunks=knowledge_chunks or [],
            reference_material=reference_material,
        )

    # ── Internal ──────────────────────────────────────────────────────

    def _assemble(
        self,
        session_id: str,
        current_query: str,
        user_profile: list[dict],
        relevant_memories: list[dict],
        knowledge_chunks: list[dict],
        reference_material: str,
    ) -> AssembledContext:
        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            session_state = default_session_state_for_type("general")
            recent_turns: list[dict] = []
        else:
            session_state = parse_session_state(
                meta["session_state"],
                meta.get("session_type", "general"),
            )
            recent_turns = transcript_service.get_recent_turns(
                session_id=session_id,
                max_turns=self.DEFAULT_RECENT_TURNS,
                after_seq=meta["compaction_cursor"],
            )

        cleaned = self._repair_pairs(
            trim_messages(self._sanitize(recent_turns), self.budget.RECENT_TURNS_BUDGET)
        )

        # Build retrieved_context from memories + knowledge
        retrieved_parts: list[str] = []
        if relevant_memories:
            trimmed_memories = trim_items(
                relevant_memories, content_key="content", budget=self.budget.SESSION_STATE_BUDGET,
            )
            for i, mem in enumerate(trimmed_memories, 1):
                line = (
                    f"[M{i}] [{mem.get('type', 'memory')}] "
                    f"{mem.get('description', '')}: {mem.get('content', '')}"
                )
                if mem.get("staleness_note"):
                    line += f" ({mem['staleness_note']})"
                retrieved_parts.append(line)

        if knowledge_chunks:
            trimmed_chunks = trim_items(
                knowledge_chunks, content_key="text", budget=self.budget.RETRIEVED_CONTEXT_BUDGET,
            )
            for i, chunk in enumerate(trimmed_chunks, 1):
                source = chunk.get("source_type") or chunk.get("source") or "knowledge"
                score = chunk.get("score")
                score_text = f" score={float(score):.3f}" if score is not None else ""
                retrieved_parts.append(f"[K{i}] [{source}{score_text}] {chunk.get('text', '')}")

        retrieved_context = "\n\n".join(retrieved_parts)

        ctx = AssembledContext(
            user_profile=user_profile,
            session_state=session_state,
            recent_turns=cleaned,
            retrieved_context=retrieved_context,
            reference_material=reference_material,
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
