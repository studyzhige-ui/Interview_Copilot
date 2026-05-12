"""Agent-loop context compactor for the L2 ReAct Harness.

Model-aware, boundary-safe context management pipeline used by
:class:`app.agent_runtime.query_engine.QueryEngine` to keep prompt
tokens within the model's context window across multi-turn tool
execution.

Scope: This module belongs to L2 (single-turn ReAct agent execution).
Do **not** confuse with
``app.services.chat.context_assembly_pipeline.ContextAssemblyPipeline``
which serves L1 (multi-turn dialogue context assembly).

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

Public surface:
  QueryLoopCompactor — the active class used by the agent loop.
  AgentLoopContext   — fixed-kwarg compactor (context_window /
                       threshold_ratio / protect_tail).  Was previously
                       named ``ContextPipeline`` and lived inside
                       ``query_loop_compactor.py``; renamed to
                       disambiguate from the L1 context pipeline.
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

_PRUNED_RESULT_MAX_CHARS = 200
_PRUNED_ARGS_MAX_CHARS = 200
_JSON_STRING_MAX_CHARS = 80
_MAX_COMPACT_FAILURES = 3
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
    """Create a short informational summary of a tool result."""
    char_count = len(content)
    line_count = content.count("\n") + 1
    first_line = content.split("\n", 1)[0].strip()[:120]

    result_count = "?"
    query = "?"
    url = "?"
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
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
            pass

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
    """Recursively truncate string values in a JSON-like structure."""
    if isinstance(value, str):
        if len(value) > max_str_chars:
            return value[:max_str_chars] + "...[truncated]"
        return value
    if isinstance(value, dict):
        return {k: _truncate_json_value(v, max_str_chars) for k, v in value.items()}
    if isinstance(value, list):
        items = value[:3] if len(value) > 3 else value
        result = [_truncate_json_value(item, max_str_chars) for item in items]
        if len(value) > 3:
            result.append(f"...and {len(value) - 3} more items")
        return result
    return value


def _truncate_tool_call_args_json(args_str: str) -> str:
    """JSON-safe truncation of tool_call arguments."""
    try:
        parsed = json.loads(args_str)
        truncated = _truncate_json_value(parsed)
        return json.dumps(truncated, ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, ValueError):
        if len(args_str) > _PRUNED_ARGS_MAX_CHARS:
            return args_str[:_PRUNED_ARGS_MAX_CHARS] + "...[truncated]"
        return args_str


def _estimate_message_tokens(msg: dict) -> int:
    """Rough token estimate for a single message."""
    content = msg.get("content", "")
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            content += tc.get("function", {}).get("arguments", "")
    return max(1, int(len(content) / _CHARS_PER_TOKEN))


class QueryLoopCompactor:
    """Model-aware, boundary-safe context management pipeline.

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
        self.has_attempted_reactive_compact: bool = False
        self._consecutive_compact_failures: int = 0

    # ── Layer 2: Token Warning guard ─────────────────────────────────

    def is_at_blocking_limit(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.blocking_limit

    # ── Layer 1: Pre-LLM 3-pass pruning ──────────────────────────────

    def should_compact(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.autocompact_threshold

    def pre_llm_compact(self, messages: list[dict], prompt_tokens: int) -> list[dict]:
        if not self.should_compact(prompt_tokens):
            return messages
        return self._prune_old_tool_results(messages)

    def _prune_old_tool_results(self, messages: list[dict]) -> list[dict]:
        result = list(messages)
        result = self._pass1_dedup(result)
        result = self._pass2_summarize(result)
        result = self._pass3_truncate_args(result)
        result = self._sanitize_tool_pairs(result)
        return result

    # ── Tail boundary (Hermes L1100-L1132 pattern) ───────────────────

    def _find_tail_boundary(self, messages: list[dict]) -> int:
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

        boundary = self._align_boundary_forward(messages, boundary)
        return boundary

    @staticmethod
    def _align_boundary_forward(messages: list[dict], boundary: int) -> int:
        if boundary <= 0 or boundary >= len(messages):
            return boundary

        msg = messages[boundary]

        if msg.get("role") == "tool":
            for j in range(boundary - 1, 0, -1):
                if messages[j].get("role") == "assistant" and messages[j].get("tool_calls"):
                    return j
            return boundary

        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return boundary

        return boundary

    # ── Pass 1: Dedup ────────────────────────────────────────────────

    def _pass1_dedup(self, messages: list[dict]) -> list[dict]:
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
        tool_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "tool"
        ]
        if not tool_indices:
            return messages

        tail_boundary = self._find_tail_boundary(messages)

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
        assistant_tc_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        if not assistant_tc_indices:
            return messages

        tail_boundary = self._find_tail_boundary(messages)

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
            result.append({
                "role": "tool",
                "tool_call_id": tcid,
                "content": "[Result unavailable — pruned during context management]",
            })

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
        self.has_attempted_reactive_compact = False

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
        if not tool_call_id:
            return "unknown"
        for msg in reversed(messages):
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                    return tc.get("function", {}).get("name", "unknown")
        return "unknown"


# ── Fixed-kwarg compactor (was previously named ContextPipeline) ─────────
# Reproduces the pre-refactor knobs:
#   - blocking_limit = context_window - 3_000 (no output reservation)
#   - threshold      = int(context_window * threshold_ratio)
#   - protect_tail   = fixed message count (not token budget)

_COMPAT_TOKEN_WARNING_BUFFER = 3_000


class AgentLoopContext(QueryLoopCompactor):
    """Fixed-kwarg compactor (``context_window`` / ``threshold_ratio`` / ``protect_tail``).

    Disambiguated from the L1 :class:`ContextAssemblyPipeline` (multi-turn
    dialogue context assembly).
    """

    def __init__(
        self,
        *,
        threshold_ratio: float = 0.65,
        context_window: int = 1_000_000,
        protect_tail: int = 4,
    ):
        from app.core.model_registry import ModelProfile

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
            tail_budget_tokens=999_999_999,
        )
        self.autocompact_threshold = int(context_window * threshold_ratio)
        self.blocking_limit = context_window - _COMPAT_TOKEN_WARNING_BUFFER
        self._protect_tail_count = protect_tail

    def _find_tail_boundary(self, messages: list[dict]) -> int:
        """Override: use fixed message count (legacy behavior)."""
        tool_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "tool"
        ]
        if len(tool_indices) <= self._protect_tail_count:
            return len(messages)

        protected_start = tool_indices[-self._protect_tail_count]
        return self._align_boundary_forward(messages, protected_start)

    def _pass3_truncate_args(self, messages: list[dict]) -> list[dict]:
        """Override: fixed message count + raw char truncation (legacy)."""
        assistant_tc_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        if len(assistant_tc_indices) <= self._protect_tail_count:
            return messages

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


__all__ = ["QueryLoopCompactor", "AgentLoopContext"]
