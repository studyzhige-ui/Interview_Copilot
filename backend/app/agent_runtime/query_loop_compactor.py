"""Query-loop context compactor for the Agent Harness.

Model-aware, boundary-safe context management pipeline that replaces
the original ``ContextPipeline``.  All token budgets are derived from
``ModelProfile`` via ``context_window`` functions — no hardcoded constants.

Design references:
  Claude Code 5+1 layer architecture (query.ts):
    ⓪ Tool Result Budget — per-message persistence
    ① Snip — history trimming (N/A for web)
    ② Microcompact — old tool_result clearing → adapted as 3-pass pruning
    ③ Context Collapse — segment folding (N/A for 1M window)
    ④ Autocompact — LLM summarization (future Phase: LLM compact)
    ⑤ Token Warning — blocking limit guard → is_at_blocking_limit()
    ⑥ Reactive Compact — post-error compression → on_context_too_long()

  Hermes context_compressor.py:
    - 3-pass tool result pruning: dedup → summarize → truncate args
    - Token-budget tail boundary (L1100-L1132)
    - JSON-safe argument truncation (L151-L194)
    - Orphan tool pair sanitization (L1040-L1098)
    - Anti-thrashing circuit breaker

Pipeline layers:
  Layer 0 (pre-LLM): Tool result persistence & turn budget enforcement.
    Handled by ``tool_result_storage`` module — applied in the main loop
    before messages are appended.

  Layer 1 (pre-LLM): 3-pass old tool result pruning (Hermes pattern).
    Pass 1: Deduplicate identical tool results (content hash).
    Pass 2: Summarize old tool results outside the protected tail.
    Pass 3: JSON-safe truncation of old assistant tool_call arguments.
    Post: Orphan tool pair sanitization.
    All passes operate on a COPY — original messages are never modified.

  Layer 2 (pre-LLM): Token Warning guard (Claude Code ⑤).
    Block the LLM call entirely when prompt_tokens approach the hard
    context window limit, avoiding a wasted API request.

  Layer 3 (post-LLM): Reactive compact on context_too_long error.
    Emergency compression with circuit breaker protection.

Backward compatibility:
  ``ContextPipeline`` is re-exported as an alias so existing imports
  (tests, etc.) continue to work without modification.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from app.agent_runtime.context_window import (
    TAIL_BUDGET_TOKENS,
    get_autocompact_threshold,
    get_blocking_limit,
)

if TYPE_CHECKING:
    from app.core.model_registry import ModelProfile

logger = logging.getLogger(__name__)

# ── Pruning constants ────────────────────────────────────────────────────

# Maximum chars kept per pruned tool result summary.
_PRUNED_RESULT_MAX_CHARS = 200

# Maximum chars kept per pruned tool_call arguments (JSON-safe fallback).
_PRUNED_ARGS_MAX_CHARS = 200

# Recursive JSON string value truncation limit.
_JSON_STRING_MAX_CHARS = 80

# Circuit breaker: max consecutive compact failures before refusing retry.
# Claude Code uses 3 (autocompact circuit breaker); Hermes uses 2.
_MAX_COMPACT_FAILURES = 3

# Approximate token-to-char ratio for CJK-heavy content.
_CHARS_PER_TOKEN = 2.5


# ── Tool-specific summary templates (Hermes L197-L316 pattern) ───────────

_TOOL_SUMMARY_TEMPLATES: dict[str, str] = {
    "web_search": (
        "[web_search result pruned] query={query} | "
        "{result_count} results | first: {preview}"
    ),
    "read_url": (
        "[read_url result pruned] url={url} | "
        "{char_count} chars extracted | preview: {preview}"
    ),
    "search_knowledge": (
        "[search_knowledge result pruned] query={query} | "
        "{result_count} chunks | preview: {preview}"
    ),
    "read_interview_history": (
        "[read_interview_history result pruned] "
        "{result_count} interviews | preview: {preview}"
    ),
    "search_jobs": (
        "[search_jobs result pruned] query={query} | "
        "{result_count} jobs | preview: {preview}"
    ),
}


def _summarize_tool_result(tool_name: str, content: str) -> str:
    """Create a short informational summary of a tool result.

    Uses tool-specific templates when available (Hermes L197-L316);
    falls back to a generic structured summary otherwise.
    """
    char_count = len(content)
    line_count = content.count("\n") + 1
    first_line = content.split("\n", 1)[0].strip()[:120]

    # Try to extract structured info for template rendering
    result_count = "?"
    query = "?"
    url = "?"
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            # Common patterns in our tool results
            result_count = str(
                parsed.get("count", parsed.get("total", len(parsed)))
            )
            query = str(parsed.get("query", "?"))[:60]
            url = str(parsed.get("url", "?"))[:80]
        elif isinstance(parsed, list):
            result_count = str(len(parsed))
    except (json.JSONDecodeError, ValueError):
        pass

    preview = first_line[:80]

    # Use tool-specific template if available
    template = _TOOL_SUMMARY_TEMPLATES.get(tool_name)
    if template:
        try:
            return template.format(
                query=query,
                url=url,
                result_count=result_count,
                char_count=char_count,
                preview=preview,
            )
        except (KeyError, IndexError):
            pass  # fall through to generic

    # Generic summary (original pattern)
    result_type = "text"
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            keys = list(parsed.keys())[:5]
            result_type = f"json object with keys: {keys}"
        elif isinstance(parsed, list):
            result_type = f"json array with {len(parsed)} items"
    except (json.JSONDecodeError, ValueError):
        pass

    return (
        f"[Tool result pruned for context management]\n"
        f"Tool: {tool_name}\n"
        f"Result type: {result_type}\n"
        f"Size: {char_count} chars, {line_count} lines\n"
        f"Preview: {first_line}"
    )


def _content_hash(content: str) -> str:
    """Hash the first 200 chars of content for dedup detection."""
    return hashlib.md5(content[:200].encode("utf-8", errors="replace")).hexdigest()


def _truncate_json_value(value, max_str_chars: int = _JSON_STRING_MAX_CHARS):
    """Recursively truncate string values in a JSON-like structure.

    Hermes L151-L194 pattern: parse JSON → walk → truncate strings →
    re-serialize.  Never breaks JSON structure.
    """
    if isinstance(value, str):
        if len(value) > max_str_chars:
            return value[:max_str_chars] + "...[truncated]"
        return value
    if isinstance(value, dict):
        return {k: _truncate_json_value(v, max_str_chars) for k, v in value.items()}
    if isinstance(value, list):
        # For large lists, keep only first 3 items
        items = value[:3] if len(value) > 3 else value
        result = [_truncate_json_value(item, max_str_chars) for item in items]
        if len(value) > 3:
            result.append(f"...and {len(value) - 3} more items")
        return result
    return value  # numbers, booleans, null — pass through


def _truncate_tool_call_args_json(args_str: str) -> str:
    """JSON-safe truncation of tool_call arguments.

    Hermes L151-L194: parse → recursive string truncation → re-serialize.
    Falls back to raw char truncation only if JSON parsing fails.
    """
    try:
        parsed = json.loads(args_str)
        truncated = _truncate_json_value(parsed)
        return json.dumps(truncated, ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, ValueError):
        # Fallback: raw char truncation (old behavior)
        if len(args_str) > _PRUNED_ARGS_MAX_CHARS:
            return args_str[:_PRUNED_ARGS_MAX_CHARS] + "...[truncated]"
        return args_str


def _estimate_message_tokens(msg: dict) -> int:
    """Rough token estimate for a single message.

    Uses char count / _CHARS_PER_TOKEN as a fast proxy.  Accurate enough
    for tail boundary decisions; the real token count comes from API usage.
    """
    content = msg.get("content", "")
    # Also count tool_call arguments
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            content += tc.get("function", {}).get("arguments", "")
    return max(1, int(len(content) / _CHARS_PER_TOKEN))


class QueryLoopCompactor:
    """Model-aware, boundary-safe context management pipeline.

    Replaces ``ContextPipeline`` with dynamic token budgets derived
    from ``ModelProfile``.

    Layer 0: tool result persistence (pre-LLM, handled externally)
    Layer 1: 3-pass old result pruning + orphan sanitization (pre-LLM)
    Layer 2: token warning guard (pre-LLM, ``is_at_blocking_limit``)
    Layer 3: reactive compact on 413 (post-LLM, ``on_context_too_long``)

    All pruning operations produce NEW lists and dicts — the original
    messages list is never modified (copy-on-write semantics).
    """

    def __init__(
        self,
        profile: ModelProfile,
        *,
        tail_budget_tokens: int = TAIL_BUDGET_TOKENS,
    ):
        self.profile = profile
        self.autocompact_threshold = get_autocompact_threshold(profile)
        self.blocking_limit = get_blocking_limit(profile)
        self.tail_budget_tokens = tail_budget_tokens
        # Claude Code pattern: prevent infinite reactive-compact loops
        self.has_attempted_reactive_compact: bool = False
        # Circuit breaker: consecutive compact failures
        self._consecutive_compact_failures: int = 0

    # ── Layer 2: Token Warning guard ─────────────────────────────────

    def is_at_blocking_limit(self, prompt_tokens: int) -> bool:
        """Check if prompt_tokens are at the blocking limit.

        When True, the agent loop should STOP instead of making a
        doomed LLM call.  This is Claude Code's ``calculateTokenWarningState``
        with ``isAtBlockingLimit`` (query.ts L637).
        """
        return prompt_tokens >= self.blocking_limit

    # ── Layer 1: Pre-LLM 3-pass pruning ──────────────────────────────

    def should_compact(self, prompt_tokens: int) -> bool:
        """Check if prompt_tokens exceed the compaction threshold."""
        return prompt_tokens >= self.autocompact_threshold

    def pre_llm_compact(self, messages: list[dict], prompt_tokens: int) -> list[dict]:
        """Layer 1: 3-pass pruning if approaching context limit.

        Called after each tool batch, before the next LLM call.  Only
        activates when prompt_tokens exceed the threshold.

        Returns a NEW list — original messages are never modified.
        """
        if not self.should_compact(prompt_tokens):
            return messages
        return self._prune_old_tool_results(messages)

    def _prune_old_tool_results(self, messages: list[dict]) -> list[dict]:
        """3-pass pruning pipeline + orphan sanitization.

        All passes operate on copies — original messages are never modified.

        Pass 1 (dedup): Remove duplicate tool results.
        Pass 2 (summarize): Replace old tool results with summaries.
        Pass 3 (truncate args): JSON-safe truncation of old arguments.
        Post: Orphan tool pair sanitization.
        """
        result = list(messages)
        result = self._pass1_dedup(result)
        result = self._pass2_summarize(result)
        result = self._pass3_truncate_args(result)
        result = self._sanitize_tool_pairs(result)
        return result

    # ── Tail boundary (Hermes L1100-L1132 pattern) ───────────────────

    def _find_tail_boundary(self, messages: list[dict]) -> int:
        """Find the boundary index: messages[boundary:] are protected.

        Uses a token budget (not fixed message count) to determine the
        tail.  Walks backward from the end, accumulating estimated tokens
        until the tail budget is exhausted.

        Returns the first index of the protected tail region.
        """
        if not messages:
            return 0

        budget_remaining = self.tail_budget_tokens
        boundary = len(messages)

        for i in range(len(messages) - 1, 0, -1):
            msg = messages[i]
            cost = _estimate_message_tokens(msg)
            if budget_remaining - cost < 0 and boundary < len(messages):
                break
            budget_remaining -= cost
            boundary = i

        # Align boundary forward to avoid splitting tool call/result groups
        boundary = self._align_boundary_forward(messages, boundary)
        return boundary

    @staticmethod
    def _align_boundary_forward(messages: list[dict], boundary: int) -> int:
        """Align boundary forward to not split tool_call/result pairs.

        Hermes L1100-L1120 pattern: if boundary falls on a tool result,
        move it backward to include the preceding assistant tool_call.
        If boundary falls on an assistant with tool_calls, include it
        in the protected tail (move boundary backward).
        """
        if boundary <= 0 or boundary >= len(messages):
            return boundary

        msg = messages[boundary]

        # If boundary is on a tool result, the assistant+tool_calls before
        # it must also be protected
        if msg.get("role") == "tool":
            # Walk backward to find the assistant message with the matching tool_call
            for j in range(boundary - 1, 0, -1):
                if messages[j].get("role") == "assistant" and messages[j].get("tool_calls"):
                    return j
            return boundary

        # If boundary is on an assistant with tool_calls, protect from here
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return boundary

        return boundary

    # ── Pass 1: Dedup ────────────────────────────────────────────────

    def _pass1_dedup(self, messages: list[dict]) -> list[dict]:
        """Pass 1: Deduplicate identical tool results.

        When the same tool produces the same content (by hash of first
        200 chars) multiple times, only the LAST occurrence is kept.
        """
        tool_indices = [
            i for i, m in enumerate(messages) if m.get("role") == "tool"
        ]
        if len(tool_indices) <= 1:
            return messages

        sig_to_indices: dict[tuple[str, str], list[int]] = {}
        for i in tool_indices:
            msg = messages[i]
            content = msg.get("content", "")
            tool_name = self._find_tool_name(messages, msg.get("tool_call_id", ""))
            sig = (tool_name, _content_hash(content))
            sig_to_indices.setdefault(sig, []).append(i)

        dedup_set: set[int] = set()
        for indices in sig_to_indices.values():
            if len(indices) > 1:
                dedup_set.update(indices[:-1])

        if not dedup_set:
            return messages

        result = []
        dedup_count = 0
        for i, msg in enumerate(messages):
            if i in dedup_set:
                msg = {
                    **msg,
                    "content": "[Duplicate result removed — see later call]",
                }
                dedup_count += 1
            result.append(msg)

        if dedup_count > 0:
            logger.info("Pass 1 (dedup): removed %d duplicate tool results", dedup_count)
        return result

    # ── Pass 2: Summarize ────────────────────────────────────────────

    def _pass2_summarize(self, messages: list[dict]) -> list[dict]:
        """Pass 2: Replace old tool-result contents with summaries.

        Uses token-budget tail boundary instead of fixed message count.
        Tool-specific summary templates produce more informative summaries.
        """
        tool_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "tool"
        ]
        if not tool_indices:
            return messages

        tail_boundary = self._find_tail_boundary(messages)

        # Only prune tool results BEFORE the tail boundary
        prune_set = {i for i in tool_indices if i < tail_boundary}

        if not prune_set:
            return messages

        pruned = []
        pruned_count = 0
        for i, msg in enumerate(messages):
            if i in prune_set:
                content = msg.get("content", "")
                if len(content) > _PRUNED_RESULT_MAX_CHARS:
                    tool_name = self._find_tool_name(
                        messages, msg.get("tool_call_id", "")
                    )
                    msg = {
                        **msg,
                        "content": _summarize_tool_result(tool_name, content),
                    }
                    pruned_count += 1
            pruned.append(msg)

        if pruned_count > 0:
            logger.info(
                "Pass 2 (summarize): pruned %d old tool results (tail boundary=%d)",
                pruned_count,
                tail_boundary,
            )
        return pruned

    # ── Pass 3: Truncate args (JSON-safe) ────────────────────────────

    def _pass3_truncate_args(self, messages: list[dict]) -> list[dict]:
        """Pass 3: JSON-safe truncation of old assistant tool_call arguments.

        Uses JSON-aware recursive truncation (Hermes L151-L194) instead
        of raw char slicing.  This preserves valid JSON structure.
        """
        assistant_tc_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        if not assistant_tc_indices:
            return messages

        tail_boundary = self._find_tail_boundary(messages)

        # Only truncate args BEFORE the tail boundary
        truncate_set = {i for i in assistant_tc_indices if i < tail_boundary}

        if not truncate_set:
            return messages

        result = []
        truncated_count = 0
        for i, msg in enumerate(messages):
            if i in truncate_set:
                tool_calls = msg.get("tool_calls", [])
                new_tool_calls = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        new_tool_calls.append(tc)
                        continue
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "")
                    if len(args_str) > _PRUNED_ARGS_MAX_CHARS:
                        tc = {
                            **tc,
                            "function": {
                                **func,
                                "arguments": _truncate_tool_call_args_json(args_str),
                            },
                        }
                        truncated_count += 1
                    new_tool_calls.append(tc)
                if new_tool_calls != tool_calls:
                    msg = {**msg, "tool_calls": new_tool_calls}
            result.append(msg)

        if truncated_count > 0:
            logger.info(
                "Pass 3 (truncate args): JSON-safe truncated %d old tool_call arguments",
                truncated_count,
            )
        return result

    # ── Orphan tool pair sanitization (Hermes L1040-L1098) ───────────

    @staticmethod
    def _sanitize_tool_pairs(messages: list[dict]) -> list[dict]:
        """Fix orphaned tool_call/result pairs after pruning.

        Hermes L1040-L1098 pattern: ensure every tool result has a
        matching tool_call in a preceding assistant message, and every
        tool_call has a matching tool result.

        Orphaned messages cause API errors.  This pass adds placeholder
        messages to fix broken pairs.
        """
        # Collect all tool_call IDs from assistant messages
        call_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    if isinstance(tc, dict) and tc.get("id"):
                        call_ids.add(tc["id"])

        # Collect all tool_call_ids from tool result messages
        result_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tcid = msg.get("tool_call_id")
                if tcid:
                    result_ids.add(tcid)

        # Find orphaned results (tool result with no matching call)
        orphaned_results = result_ids - call_ids
        # Find orphaned calls (tool call with no matching result)
        orphaned_calls = call_ids - result_ids

        if not orphaned_results and not orphaned_calls:
            return messages

        result = list(messages)

        # For orphaned calls: append placeholder tool results
        for tcid in orphaned_calls:
            result.append({
                "role": "tool",
                "tool_call_id": tcid,
                "content": "[Result unavailable — pruned during context management]",
            })

        # For orphaned results: remove them (they'll cause API errors)
        if orphaned_results:
            result = [
                msg for msg in result
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

    # ── Layer 3: Reactive compact on context_too_long ────────────────

    def on_context_too_long(
        self,
        messages: list[dict],
    ) -> tuple[list[dict], bool]:
        """Layer 3: emergency compression when API returns context_too_long.

        Returns (messages, should_retry).

        Protection mechanisms:
          1. ``has_attempted_reactive_compact`` prevents infinite loops
             (Claude Code ``hasAttemptedReactiveCompact``, query.ts:1157).
          2. Circuit breaker: after ``_MAX_COMPACT_FAILURES`` consecutive
             failures, refuse further compression.

        Returns a NEW list — original messages are never modified.
        """
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
        messages = self._prune_old_tool_results(messages)
        logger.info(
            "Reactive compact applied (failure count: %d/%d) — will retry LLM call",
            self._consecutive_compact_failures,
            _MAX_COMPACT_FAILURES,
        )
        return messages, True

    def reset_reactive_flag(self) -> None:
        """Reset the per-step reactive compact flag.

        Called after each successful LLM call so that reactive compact
        can be attempted again on the NEXT step if needed.
        """
        self.has_attempted_reactive_compact = False

    def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker after a successful LLM call.

        Called by the agent loop when an LLM call succeeds, indicating
        that context pressure is manageable.
        """
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
        """Walk backwards to find the tool name for a given tool_call_id."""
        if not tool_call_id:
            return "unknown"
        for msg in reversed(messages):
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                    return tc.get("function", {}).get("name", "unknown")
        return "unknown"


# ── Backward compatibility alias ─────────────────────────────────────────
# Existing tests and code that import ``ContextPipeline`` will continue to
# work.  This subclass reproduces the EXACT old behavior while delegating
# core pruning logic to ``QueryLoopCompactor``.

# Old constants reproduced for compat
_COMPAT_TOKEN_WARNING_BUFFER = 3_000


class ContextPipeline(QueryLoopCompactor):
    """Backward-compatible alias for QueryLoopCompactor.

    Accepts the same kwargs as the old ContextPipeline constructor
    (context_window, threshold_ratio, protect_tail) and reproduces
    exactly the old behavior:
      - blocking_limit = context_window - 3_000 (no output reservation)
      - threshold = int(context_window * threshold_ratio)
      - protect_tail = fixed message count (not token budget)
    """

    def __init__(
        self,
        *,
        threshold_ratio: float = 0.65,
        context_window: int = 1_000_000,
        protect_tail: int = 4,
    ):
        from app.core.model_registry import ModelProfile

        # Build a synthetic profile with max_output_tokens=0 so that
        # get_effective_window returns context_window directly, and
        # blocking_limit = context_window - 3000 (old behavior).
        profile = ModelProfile(
            id="legacy-compat",
            provider="deepseek",
            display_name="Legacy Compat",
            model="deepseek-v4-pro",
            api_base="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
            context_window=context_window,
            max_output_tokens=0,
        )
        super().__init__(
            profile=profile,
            # Use a very large tail budget so it never kicks in;
            # we override _find_tail_boundary below.
            tail_budget_tokens=999_999_999,
        )
        # Override computed thresholds with old formula
        self.autocompact_threshold = int(context_window * threshold_ratio)
        self.blocking_limit = context_window - _COMPAT_TOKEN_WARNING_BUFFER
        # Store fixed protect_tail for message-count-based boundary
        self._protect_tail_count = protect_tail

    def _find_tail_boundary(self, messages: list[dict]) -> int:
        """Override: use fixed message count (old behavior).

        Protects the last N tool-result messages and N assistant messages
        with tool_calls, matching the old ContextPipeline semantics.
        """
        # Find all tool-result indices
        tool_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "tool"
        ]
        if len(tool_indices) <= self._protect_tail_count:
            return len(messages)  # protect everything

        # Boundary is just before the Nth-from-last tool result
        protected_start = tool_indices[-self._protect_tail_count]
        # Also protect the preceding assistant message
        return self._align_boundary_forward(messages, protected_start)

    def _pass3_truncate_args(self, messages: list[dict]) -> list[dict]:
        """Override: use fixed message count for tail (old behavior).

        Also uses raw char truncation instead of JSON-safe truncation
        to match old test expectations.
        """
        assistant_tc_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        if len(assistant_tc_indices) <= self._protect_tail_count:
            return messages

        # Truncate all except the most recent N
        truncate_set = set(assistant_tc_indices[: -self._protect_tail_count])

        result = []
        truncated_count = 0
        for i, msg in enumerate(messages):
            if i in truncate_set:
                tool_calls = msg.get("tool_calls", [])
                new_tool_calls = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        new_tool_calls.append(tc)
                        continue
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "")
                    if len(args_str) > _PRUNED_ARGS_MAX_CHARS:
                        tc = {
                            **tc,
                            "function": {
                                **func,
                                "arguments": args_str[:_PRUNED_ARGS_MAX_CHARS] + "...[truncated]",
                            },
                        }
                        truncated_count += 1
                    new_tool_calls.append(tc)
                if new_tool_calls != tool_calls:
                    msg = {**msg, "tool_calls": new_tool_calls}
            result.append(msg)

        if truncated_count > 0:
            logger.info(
                "Pass 3 (truncate args): truncated %d old tool_call arguments",
                truncated_count,
            )
        return result

