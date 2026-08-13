"""L2 agent-loop context compaction.

Used by :class:`app.conversation.agent_strategy.AgentLoopStrategy` to keep
prompt tokens within the model's context window during multi-turn tool
execution.  The entry point is :meth:`QueryLoopCompactor.compress`, which runs
two pressure-gated phases on a copy of the running message list:

  Phase 1  cheap microcompact (runs only under context pressure, zero-LLM):
             Delete old compactable tool results, keeping only the most
             recent ``_KEEP_RECENT`` globally.  Persisted (<persisted-output>)
             results are exempt.  Orphaned tool_call ↔ tool_result pairs are
             repaired afterwards.
  Phase 2  LLM autocompact (runs ONLY when over threshold):
             Summarize the history into one reference-only message when the
             cheap pass can't get under the threshold.

The provider-neutral implementation deliberately does not depend on Claude's
private cache-editing paths. It preserves semantics when no provider-specific
context editing exists and only discards replaceable payloads when the active
request has crossed the configured pressure threshold.

Scope: L2 (a single ReAct execution).  Distinct from
``app.services.chat.context_assembly_pipeline`` (L1 multi-turn prompt
assembly); uses the canonical token counter from
``app.core.tokens``.
"""

from __future__ import annotations

import json
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


def _unwrap_autocompact_summary(content: str) -> str | None:
    marker = "[Historical Context Summary]"
    end_marker = "--- END OF CONTEXT SUMMARY ---"
    if not content.startswith(marker):
        return None
    body = content[len(marker) :]
    if end_marker in body:
        body = body.split(end_marker, 1)[0]
    # Remove the fixed reference-data warning between the marker and summary.
    paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
    return "\n\n".join(paragraphs[1:] if len(paragraphs) > 1 else paragraphs)


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


class QueryLoopCompactor:
    """Pressure-gated microcompact + autocompact for one Agent loop.

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
        # Owner of the conversation — the autocompact summarizer resolves the
        # platform worker model; user answer-model credentials never apply.
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
        self._consecutive_compact_failures: int = 0
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
        """Proactive pre-LLM compaction (Phase 1 → Phase 2).

        Both phases are skipped while the complete provider request is below
        the pressure threshold. Once crossed, the cheap pass runs first and
        the LLM pass is used only if the request remains over budget.

        Returns ``(messages, at_blocking_limit)``.
        """
        total = self._measure_tokens(messages)
        if not self.should_compact(total):
            return messages, self.is_at_blocking_limit(total)

        # Phase 1 — pressure-gated cheap microcompact.
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

    # ── Phase 1: cheap microcompact (pressure-gated) ─────────────────

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

        Preserves the leading system block + the *current* task-defining user
        query, then replaces older history/work with a single LLM summary,
        keeping the last ``keep_last`` post-task messages verbatim.
        """
        # Repair any pre-existing orphan before choosing the summary boundary;
        # neither the summary input nor the retained tail may contain half of a
        # Tool Call/Result pair.
        messages = self._sanitize_tool_pairs(messages)
        original_messages = messages
        stable_head: list[dict] = []
        previous_summaries: list[str] = []
        source_head_end = 0
        while (
            source_head_end < len(messages)
            and messages[source_head_end].get("role") == "system"
        ):
            message = messages[source_head_end]
            previous = _unwrap_autocompact_summary(str(message.get("content") or ""))
            if previous is None:
                stable_head.append(message)
            elif previous:
                previous_summaries.append(previous)
            source_head_end += 1
        if previous_summaries:
            messages = stable_head + messages[source_head_end:]
        head_end = len(stable_head)
        task_index = next(
            (
                index
                for index, message in enumerate(messages)
                if message is self.task_anchor
            ),
            None,
        )
        if task_index is None:
            # Compatibility fallback for direct compactor callers.  The latest
            # user message is a safer task anchor than the first historical
            # user turn, which was the old source of cross-turn task drift.
            task_index = next(
                (
                    index
                    for index in range(len(messages) - 1, head_end - 1, -1)
                    if messages[index].get("role") == "user"
                ),
                None,
            )

        post_task_start = task_index + 1 if task_index is not None else head_end
        tail_start = self._pair_safe_tail_start(
            messages,
            max(post_task_start, len(messages) - keep_last),
            minimum=post_task_start,
        )
        tail = messages[tail_start:]
        to_summarize = [
            message
            for index, message in enumerate(messages)
            if index >= head_end and index != task_index and index < tail_start
        ]
        if not to_summarize:
            return original_messages
        conversation = "\n\n".join(
            f"{m.get('role', '?')}: {_message_text(m)}" for m in to_summarize
        )

        from app.services.chat.conversation_summarizer import summarize_conversation

        summary = await summarize_conversation(
            "\n\n".join(previous_summaries),
            conversation,
            user_id=self.user_id,
        )
        if not summary:
            return original_messages

        # A compaction summary is a lossy Conversation projection, not a new
        # system rule or a Runtime checkpoint. Keeping it in the chronological
        # message stream prevents it from gaining instruction authority.
        summary_msg = {
            "role": "user",
            "content": AUTOCOMPACT_SUMMARY_WRAPPER.format(summary=summary),
        }
        logger.info(
            "autocompact: summarized %d messages → 1 summary + %d kept verbatim",
            len(to_summarize),
            len(tail),
        )
        task = [messages[task_index]] if task_index is not None else []
        return messages[:head_end] + [summary_msg] + task + tail

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

    @staticmethod
    def _pair_safe_tail_start(
        messages: list[dict],
        tail_start: int,
        *,
        minimum: int,
    ) -> int:
        """Move a tail boundary past complete Tool pairs until none crosses."""
        call_positions: dict[str, int] = {}
        result_positions: dict[str, int] = {}
        for index, message in enumerate(messages):
            if message.get("role") == "assistant":
                for tool_call in message.get("tool_calls", []):
                    if isinstance(tool_call, dict) and tool_call.get("id"):
                        call_positions[str(tool_call["id"])] = index
            elif message.get("role") == "tool" and message.get("tool_call_id"):
                result_positions[str(message["tool_call_id"])] = index

        adjusted = max(minimum, tail_start)
        while True:
            crossings = [
                result_positions[call_id] + 1
                for call_id, call_index in call_positions.items()
                if call_index < adjusted <= result_positions.get(call_id, -1)
            ]
            if not crossings:
                return adjusted
            adjusted = max(adjusted, max(crossings))

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
