"""L2 agent-loop context compaction.

Used by :class:`app.conversation.agent_strategy.AgentLoopStrategy` to keep
prompt tokens within the model's context window during multi-turn tool
execution.  The entry point is :meth:`QueryLoopCompactor.compress`, which runs
two phases on a copy of the running message list:

  Phase 1  cheap microcompact (runs UNCONDITIONALLY, zero-LLM):
             Delete old compactable tool results, keeping only the most
             recent ``_KEEP_RECENT`` globally.  Persisted (<persisted-output>)
             results are exempt.  Orphaned tool_call ↔ tool_result pairs are
             repaired afterwards.
  Phase 2  LLM autocompact (runs ONLY when over threshold):
             Summarize the history into one reference-only message when the
             cheap pass can't get under the threshold.

Aligned with Claude Code's microcompact design: an explicit set of
compactable tool types, position-based keep-last-N, unconditional execution.

Scope: L2 (a single ReAct execution).  Distinct from
``app.services.chat.context_assembly_pipeline`` (L1 multi-turn prompt
assembly); uses the canonical token counter from
``app.core.tokens``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.agent_runtime.context_window import (
    get_blocking_limit,
    get_cheap_prepass_threshold,
)
from app.agent_runtime.tool_result_storage import is_persisted_content
from app.core.tokens import token_count
from app.prompts.chat import AUTOCOMPACT_SUMMARY_WRAPPER

if TYPE_CHECKING:
    from app.core.model_catalog import ModelProfile

logger = logging.getLogger(__name__)

# ── Microcompact constants ──────────────────────────────────────────────────

# Tools whose results can be deleted after use.  Aligned with Claude Code's
# COMPACTABLE_TOOLS — only "read-once" tool outputs that the model has already
# consumed in its reasoning.
COMPACTABLE_TOOLS: frozenset[str] = frozenset(
    {
        "web_search",
        "read_url",
        "read_file",
        "write_file",
        "search_knowledge",
        "read_interview_history",
        "search_jobs",
    }
)

# How many compactable tool results to keep (globally, most recent by position).
_KEEP_RECENT = 5

# Placeholder content for cleared tool results.
_CLEARED_CONTENT = "[Old tool result content cleared]"

_MAX_COMPACT_FAILURES = 3


# ── Phase 2: LLM autocompact ────────────────────────────────────────────────

_AUTOCOMPACT_KEEP_LAST = 2


def _message_text(msg: dict) -> str:
    """Flatten a message to text for summarization (content + tool-call args)."""
    parts = [str(msg.get("content") or "")]
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            parts.append(f"[call {fn.get('name', '?')}({fn.get('arguments', '')})]")
    return " ".join(p for p in parts if p)


def _estimate_message_tokens(msg: dict) -> int:
    """Token estimate for one message (content + tool_call arguments)."""
    parts = [msg.get("content") or ""]
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            parts.append(tc.get("function", {}).get("arguments", "") or "")
    return max(1, token_count("".join(parts)))


class QueryLoopCompactor:
    """Microcompact + LLM autocompact for the L2 agent loop.

    Cheap microcompact runs unconditionally on every ``compress()`` call (like
    Claude Code): delete old compactable tool results, keep last N.  LLM
    autocompact only fires when over the threshold.  All pruning produces NEW
    lists and dicts — the original messages list is never modified.
    """

    def __init__(self, profile: ModelProfile, user_id: str | None = None):
        self.profile = profile
        # Owner of the conversation — the autocompact summarizer resolves the
        # platform worker model; user answer-model credentials never apply.
        self.user_id = user_id
        self.cheap_prepass_threshold = get_cheap_prepass_threshold(profile)
        self.blocking_limit = get_blocking_limit(profile)
        self.has_attempted_reactive_compact: bool = False
        self._consecutive_compact_failures: int = 0
        # Latest autocompact summary (AGT-7): the strategy exports it via
        # result.extras so the engine can fold it into the session's
        # persistent summary — pre-fix it died with the turn and the next
        # turn re-paid the same summarize call.
        self.last_summary: str | None = None

    # ── Proactive blocking-limit guard ───────────────────────────────

    def is_at_blocking_limit(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.blocking_limit

    # ── Main entry point ─────────────────────────────────────────────

    async def compress(self, messages: list[dict]) -> tuple[list[dict], bool]:
        """Proactive pre-LLM compaction (Phase 1 → Phase 2).

        Phase 1 (cheap microcompact) runs UNCONDITIONALLY — no threshold
        check.  Phase 2 (LLM autocompact) runs only when over threshold and
        the circuit breaker is closed.

        Returns ``(messages, at_blocking_limit)``.
        """
        # Phase 1 — unconditional cheap microcompact.
        messages = self._microcompact(messages)

        total = self._measure_tokens(messages)
        if not self.should_compact(total):
            return messages, self.is_at_blocking_limit(total)

        # Phase 2 — LLM autocompact (threshold-gated + circuit-breaker).
        if self._consecutive_compact_failures < _MAX_COMPACT_FAILURES:
            messages = self._sanitize_tool_pairs(await self.autocompact(messages))
            total = self._measure_tokens(messages)
            if self.should_compact(total):
                self._consecutive_compact_failures += 1

        return messages, self.is_at_blocking_limit(total)

    # ── Phase 1: cheap microcompact (unconditional) ──────────────────

    def _microcompact(self, messages: list[dict]) -> list[dict]:
        """Delete old compactable tool results, keep last N globally.

        Walks the message list, collects all tool results from compactable
        tools (skipping persisted outputs), keeps the most recent
        ``_KEEP_RECENT`` by position, clears the rest.  Then repairs orphaned
        tool_call ↔ tool_result pairs.
        """
        compactable_indices: list[int] = []
        for i, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            tool_name = self._find_tool_name(messages, msg.get("tool_call_id", ""))
            if tool_name not in COMPACTABLE_TOOLS:
                continue
            content = msg.get("content", "")
            if is_persisted_content(content):
                continue
            if content == _CLEARED_CONTENT:
                continue
            compactable_indices.append(i)

        if len(compactable_indices) <= _KEEP_RECENT:
            return messages

        keep_set = set(compactable_indices[-_KEEP_RECENT:])
        clear_set = [i for i in compactable_indices if i not in keep_set]

        result = list(messages)
        for i in clear_set:
            result[i] = {**result[i], "content": _CLEARED_CONTENT}

        logger.info(
            "Microcompact: cleared %d old tool results, kept %d recent",
            len(clear_set),
            min(len(compactable_indices), _KEEP_RECENT),
        )
        return self._sanitize_tool_pairs(result)

    # ── Phase 2: LLM autocompact ─────────────────────────────────────

    async def autocompact(
        self, messages: list[dict], *, keep_last: int = _AUTOCOMPACT_KEEP_LAST
    ) -> list[dict]:
        """Summarize the conversation body into ONE reference-only summary msg.

        Preserves the leading system block + the task-defining user query, then
        replaces the older turns with a single LLM summary, keeping the last
        ``keep_last`` messages verbatim.
        """
        head_end = 0
        while head_end < len(messages) and messages[head_end].get("role") == "system":
            head_end += 1
        if head_end < len(messages) and messages[head_end].get("role") == "user":
            head_end += 1

        body = messages[head_end:]
        if len(body) <= keep_last:
            return messages

        to_summarize = body[:-keep_last]
        tail = body[-keep_last:]
        conversation = "\n\n".join(
            f"{m.get('role', '?')}: {_message_text(m)}" for m in to_summarize
        )

        from app.services.chat.conversation_summarizer import summarize_conversation

        summary = await summarize_conversation("", conversation, user_id=self.user_id)
        if not summary:
            return messages
        self.last_summary = summary

        summary_msg = {
            "role": "system",
            "content": AUTOCOMPACT_SUMMARY_WRAPPER.format(summary=summary),
        }
        logger.info(
            "autocompact: summarized %d messages → 1 summary + %d kept verbatim",
            len(to_summarize),
            len(tail),
        )
        return messages[:head_end] + [summary_msg] + tail

    def should_compact(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.cheap_prepass_threshold

    def _measure_tokens(self, messages: list[dict]) -> int:
        return sum(_estimate_message_tokens(m) for m in messages)

    # ── Orphan tool-pair sanitization ────────────────────────────────

    @staticmethod
    def _sanitize_tool_pairs(messages: list[dict]) -> list[dict]:
        call_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    if isinstance(tc, dict) and tc.get("id"):
                        call_ids.add(tc["id"])

        result_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tcid = msg.get("tool_call_id")
                if tcid:
                    result_ids.add(tcid)

        orphaned_results = result_ids - call_ids
        orphaned_calls = call_ids - result_ids

        if not orphaned_results and not orphaned_calls:
            return messages

        result = list(messages)

        for tcid in orphaned_calls:
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": tcid,
                    "content": "[Result unavailable — pruned during context management]",
                }
            )

        if orphaned_results:
            result = [
                msg
                for msg in result
                if not (
                    msg.get("role") == "tool"
                    and msg.get("tool_call_id") in orphaned_results
                )
            ]

        if orphaned_results or orphaned_calls:
            logger.info(
                "Sanitize tool pairs: fixed %d orphaned results, %d orphaned calls",
                len(orphaned_results),
                len(orphaned_calls),
            )
        return result

    # ── Reactive compact on context-overflow error ───────────────────

    async def on_context_too_long(
        self,
        messages: list[dict],
    ) -> tuple[list[dict], bool]:
        """Reactive recovery: force aggressive LLM autocompact + retry once."""
        if self.has_attempted_reactive_compact:
            logger.warning(
                "Reactive compact already attempted — refusing retry to prevent loop"
            )
            return messages, False

        if self._consecutive_compact_failures >= _MAX_COMPACT_FAILURES:
            logger.warning(
                "Circuit breaker open: %d consecutive compact failures — "
                "refusing retry (consider reducing task scope)",
                self._consecutive_compact_failures,
            )
            return messages, False

        self.has_attempted_reactive_compact = True
        self._consecutive_compact_failures += 1
        messages = self._sanitize_tool_pairs(
            await self.autocompact(messages, keep_last=1)
        )
        logger.info(
            "Reactive autocompact applied (failure count: %d/%d) — will retry LLM call",
            self._consecutive_compact_failures,
            _MAX_COMPACT_FAILURES,
        )
        return messages, True

    def reset_circuit_breaker(self) -> None:
        if self._consecutive_compact_failures > 0:
            logger.debug(
                "Circuit breaker reset (was at %d failures)",
                self._consecutive_compact_failures,
            )
        self._consecutive_compact_failures = 0
        self.has_attempted_reactive_compact = False

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _find_tool_name(messages: list[dict], tool_call_id: str) -> str:
        """Return the tool name for a tool_call_id."""
        if not tool_call_id:
            return "unknown"
        for msg in reversed(messages):
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                    return tc.get("function", {}).get("name", "unknown")
        return "unknown"


__all__ = ["COMPACTABLE_TOOLS", "QueryLoopCompactor"]
