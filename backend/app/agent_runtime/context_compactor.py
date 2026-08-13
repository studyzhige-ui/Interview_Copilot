"""Pressure-only reduction for the active Agent Turn projection.

Conversation summaries have exactly one owner:
``ContextAssemblyPipeline`` persists the canonical ``summary + cursor``.  The
active Agent loop must not invent a second prose summary.  When a single Turn
grows close to the provider limit this module only replaces *durably stored*
ToolResult payloads with call-identity references.  The Tool Call/Result pair
remains in the chronological projection and exact data remains available from
``AgentToolCall``.

The number of reduced results is derived from actual request pressure; there
is no unconditional or fixed-N pruning policy.  If references are not enough,
the caller stops honestly instead of silently creating another semantic owner.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.agent_runtime.context_window import (
    get_blocking_limit,
    get_cheap_prepass_threshold,
)
from app.core.tokens import token_count

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

_REFERENCE_PREFIX = "[Archived ToolResult"


def _message_text(msg: dict) -> str:
    """Flatten one message without losing Tool Call/Result correlation."""
    parts = [str(msg.get("content") or "")]
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            parts.append(
                "[tool_call "
                f"id={tc.get('id', '?')} "
                f"name={fn.get('name', '?')} "
                f"input={fn.get('arguments', '')}]"
            )
    if msg.get("role") == "tool":
        parts.insert(0, f"[tool_result id={msg.get('tool_call_id', '?')}]")
    return " ".join(p for p in parts if p)


def _request_tokens(messages: list[dict], tool_schemas: list[dict]) -> int:
    """Estimate the complete provider request, including tools exactly once."""
    payload = {"tools": tool_schemas, "messages": messages}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return max(1, token_count(encoded))


class ActiveTurnContextReducer:
    """Pressure-gated ToolResult reference reduction for one Agent loop.

    All pruning produces new lists and dictionaries; the original messages
    remain the exact in-memory execution history.
    """

    def __init__(
        self,
        profile: ModelProfile,
        user_id: str | None = None,
        *,
        task_anchor: dict | None = None,
        tool_schemas: list[dict] | None = None,
    ):
        self.profile = profile
        # Kept for a stable construction contract; reduction never calls an
        # LLM and therefore never creates a second Conversation summary.
        self.user_id = user_id
        # Exact in-memory user message that started this turn.  Identity is
        # deliberately used instead of text matching: two turns may contain
        # identical text, and loop-generated user nudges can appear after the
        # real task.  The marker never enters the provider payload.
        self.task_anchor = task_anchor
        # Concrete schemas live only in the provider ``tools`` parameter.  The
        # compactor nevertheless has to count them because the provider does.
        self.tool_schemas = list(tool_schemas or [])
        self.cheap_prepass_threshold = get_cheap_prepass_threshold(profile)
        self.blocking_limit = get_blocking_limit(profile)
        self.has_attempted_reactive_compact: bool = False
        # Provider usage is authoritative for a completed request.  Until a
        # fresh usage observation arrives, appended/pruned messages are
        # measured as a delta from that observed request.
        self._usage_prompt_tokens: int | None = None
        self._usage_request_estimate: int | None = None

    # ── Proactive blocking-limit guard ───────────────────────────────

    def is_at_blocking_limit(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.blocking_limit

    # ── Main entry point ─────────────────────────────────────────────

    async def compress(self, messages: list[dict]) -> tuple[list[dict], bool]:
        """Reduce archived ToolResult payloads only under request pressure.

        Returns ``(messages, at_blocking_limit)``.
        """
        total = self._measure_tokens(messages)
        if not self.should_compact(total):
            return messages, self.is_at_blocking_limit(total)

        messages = self._reduce_tool_results(
            messages, target=self.cheap_prepass_threshold
        )
        total = self._measure_tokens(messages)
        return messages, self.is_at_blocking_limit(total)

    # ── Phase 1: cheap microcompact (pressure-gated) ─────────────────

    def _reduce_tool_results(
        self,
        messages: list[dict],
        *,
        target: int,
    ) -> list[dict]:
        """Replace the minimum oldest ToolResult payloads needed for ``target``."""
        compactable_indices: list[int] = []
        for i, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            tool_name = self._find_tool_name(messages, msg.get("tool_call_id", ""))
            if tool_name not in COMPACTABLE_TOOLS:
                continue
            content = str(msg.get("content") or "")
            if content.startswith(_REFERENCE_PREFIX):
                continue
            compactable_indices.append(i)

        result = list(messages)
        reduced = 0
        for index in compactable_indices:
            if self._measure_tokens(result) < target:
                break
            call_id = str(result[index].get("tool_call_id") or "unknown")
            tool_name = self._find_tool_name(result, call_id)
            result[index] = {
                **result[index],
                "content": (
                    f"{_REFERENCE_PREFIX}: call_id={call_id}; tool={tool_name}. "
                    "Exact redacted result remains in the durable Tool Call record.]"
                ),
            }
            reduced += 1

        if reduced:
            logger.info(
                "Active Turn reduction archived %d ToolResult payloads", reduced
            )
        return self._sanitize_tool_pairs(result)

    def should_compact(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.cheap_prepass_threshold

    def _measure_tokens(self, messages: list[dict]) -> int:
        fresh_estimate = _request_tokens(messages, self.tool_schemas)
        if self._usage_prompt_tokens is None or self._usage_request_estimate is None:
            return fresh_estimate
        delta = fresh_estimate - self._usage_request_estimate
        return max(1, self._usage_prompt_tokens + delta)

    def observe_provider_prompt_tokens(
        self,
        prompt_tokens: int,
        messages: list[dict],
    ) -> None:
        """Anchor future measurements to provider usage plus request delta."""
        if prompt_tokens <= 0:
            return
        self._usage_prompt_tokens = int(prompt_tokens)
        self._usage_request_estimate = _request_tokens(messages, self.tool_schemas)

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
        """Reactive recovery: reference every eligible ToolResult and retry once."""
        if self.has_attempted_reactive_compact:
            logger.warning(
                "Reactive compact already attempted — refusing retry to prevent loop"
            )
            return messages, False

        self.has_attempted_reactive_compact = True
        reduced = self._reduce_tool_results(messages, target=0)
        changed = reduced != messages
        if changed:
            logger.info("Reactive ToolResult reference reduction applied")
        return reduced, changed

    def reset_circuit_breaker(self) -> None:
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


__all__ = ["ActiveTurnContextReducer", "COMPACTABLE_TOOLS"]
