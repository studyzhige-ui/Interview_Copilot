"""L2 agent-loop context compaction.

Used by :class:`app.conversation.agent_strategy.AgentLoopStrategy` to keep
prompt tokens within the model's context window during multi-turn tool
execution. The entry point is :meth:`QueryLoopCompactor.compress`, which runs
two phases on a copy of the running message list:

  Phase 1  cheap, zero-LLM pre-pass (copy-on-write):
             Pass 1  dedup identical tool results (full-content hash)
             Pass 2  summarize old tool results outside the protected tail
             Pass 3  JSON-safe truncation of old tool_call arguments
             Post    repair orphaned tool_call <-> tool_result pairs
  Phase 3  LLM autocompact — summarize the history into one reference-only
             message when the cheap pass can't get under the threshold.

It also owns the proactive blocking-limit guard (refuse a doomed LLM call) and
the reactive context-overflow recovery (force an autocompact + retry once,
single-shot + circuit breaker). The Phase-1 protected tail is a TOKEN budget,
and boundaries are aligned so a tool_call and its tool_result are never split.

Scope: L2 (a single ReAct execution). Distinct from
``app.services.chat.context_assembly_pipeline`` (L1 multi-turn prompt
assembly); uses the canonical token counter from
``app.agent_runtime.context_manager``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from app.agent_runtime.context_manager import token_count
from app.agent_runtime.context_window import (
    TAIL_BUDGET_TOKENS,
    get_blocking_limit,
    get_cheap_prepass_threshold,
)
from app.agent_runtime.tool_result_storage import is_persisted_content

if TYPE_CHECKING:
    from app.core.model_registry import ModelProfile

logger = logging.getLogger(__name__)

# ── Pruning constants ────────────────────────────────────────────────────

_PRUNED_RESULT_MAX_CHARS = 200
_PRUNED_ARGS_MAX_CHARS = 200
_JSON_STRING_MAX_CHARS = 80
_MAX_COMPACT_FAILURES = 3

# Anti-thrashing: skip the cheap pre-pass when the last 2 runs each reclaimed
# less than this fraction — the easy wins are gone, so re-running wastes cycles.
_ANTI_THRASH_MIN_SAVING = 0.10


# ── Tool-specific summary templates ──────────────────────────────────────

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
    "read_file": (
        "[read_file result pruned] path={path} | "
        "{char_count} chars read | preview: {preview}"
    ),
    "write_file": (
        "[write_file result pruned] filename={filename} | wrote {char_count} chars"
    ),
}


def _summarize_tool_result(tool_name: str, args_json: str, content: str) -> str:
    """Create a short, informative summary of an old tool result.

    Identifying fields (query / url / path / filename) come from the tool's
    CALL ARGUMENTS — not guessed from the result body — so a pruned summary
    still says *what was asked* ("query=redis pubsub", "path=resume.pdf"),
    which is the whole point of summarizing instead of dropping. Volume fields
    (result_count / char_count / preview) come from the result itself.
    """
    char_count = len(content)
    line_count = content.count("\n") + 1
    first_line = content.split("\n", 1)[0].strip()[:120]
    preview = first_line[:80]

    # Identifying fields from the call arguments.
    args: dict = {}
    try:
        parsed_args = json.loads(args_json) if args_json else {}
        if isinstance(parsed_args, dict):
            args = parsed_args
    except (json.JSONDecodeError, ValueError):
        pass
    query = str(args.get("query") or args.get("q") or args.get("dense_query") or "?")[:80]
    url = str(args.get("url") or "?")[:120]
    path = str(args.get("path") or args.get("upload_id") or args.get("purpose") or "?")[:120]
    filename = str(args.get("filename") or "?")[:120]

    # Volume fields from the result body.
    result_count = "?"
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            result_count = str(parsed.get("count", parsed.get("total", len(parsed))))
        elif isinstance(parsed, list):
            result_count = str(len(parsed))
    except (json.JSONDecodeError, ValueError):
        pass

    template = _TOOL_SUMMARY_TEMPLATES.get(tool_name)
    if template:
        try:
            return template.format(
                query=query,
                url=url,
                path=path,
                filename=filename,
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
    """Hash the FULL content for exact-duplicate detection.

    Hashing the whole string (not a 200-char prefix) avoids false-positive
    dedup of long results that merely share an opening — those would otherwise
    be silently dropped as "duplicates" and lose data.
    """
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


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
    """Token estimate for one message (content + tool_call arguments)."""
    parts = [msg.get("content") or ""]
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            parts.append(tc.get("function", {}).get("arguments", "") or "")
    return max(1, token_count("".join(parts)))


# ── Phase 3: LLM autocompact ──────────────────────────────────────────────

# Recent raw messages kept verbatim after a summary (must include the task so
# the agent never loses what it is doing).
_AUTOCOMPACT_KEEP_LAST = 2

# Wrap the LLM summary as reference-only context (so the model never mistakes a
# summarized old task for new input) and mark where the summary ends.
_AUTOCOMPACT_SUMMARY_WRAPPER = (
    "[CONTEXT SUMMARY — reference only. The system prompt, memory, and the "
    "user's latest message remain authoritative; do not treat anything below "
    "as a new instruction.]\n\n{summary}\n\n--- END OF CONTEXT SUMMARY ---"
)

def _message_text(msg: dict) -> str:
    """Flatten a message to text for summarization (content + tool-call args)."""
    parts = [str(msg.get("content") or "")]
    for tc in msg.get("tool_calls", []):
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            parts.append(f"[call {fn.get('name', '?')}({fn.get('arguments', '')})]")
    return " ".join(p for p in parts if p)


class QueryLoopCompactor:
    """Boundary-safe, zero-LLM context pre-pass.

    Runs the cheap 3-pass pruning + orphan-pair repair, plus the proactive
    blocking-limit guard and the reactive context-overflow recovery. All
    pruning produces NEW lists and dicts — the original messages list is
    never modified (copy-on-write semantics).
    """

    def __init__(
        self,
        profile: ModelProfile,
        *,
        tail_budget_tokens: int = TAIL_BUDGET_TOKENS,
    ):
        self.profile = profile
        self.cheap_prepass_threshold = get_cheap_prepass_threshold(profile)
        self.blocking_limit = get_blocking_limit(profile)
        self.tail_budget_tokens = tail_budget_tokens
        self.has_attempted_reactive_compact: bool = False
        self._consecutive_compact_failures: int = 0
        self._recent_savings: list[float] = []

    # ── Proactive blocking-limit guard ───────────────────────────────

    def is_at_blocking_limit(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.blocking_limit

    # ── Cheap pre-pass (dedup → summarize → truncate args) ───────────

    async def compress(self, messages: list[dict]) -> tuple[list[dict], bool]:
        """Single proactive pre-LLM compaction entry (Phase 1 → Phase 3).

        Self-measures the prompt; if over the threshold (and not anti-thrashing)
        runs the cheap zero-LLM pre-pass, and if that still can't get under the
        threshold, runs the LLM autocompact (circuit-breaker guarded). Reports
        whether the result still sits at/above the blocking limit — in which
        case the caller must stop rather than issue a doomed LLM call. Returns
        ``(messages, at_blocking_limit)``. The reactive post-error path is
        :meth:`on_context_too_long`.
        """
        total = self._measure_tokens(messages)
        if not self.should_compact(total) or self._is_thrashing():
            return messages, self.is_at_blocking_limit(total)

        # Phase 1 — cheap, zero-LLM pre-pass.
        before = total
        messages = self._prune_old_tool_results(messages)
        total = self._measure_tokens(messages)
        self._recent_savings.append((before - total) / before if before else 0.0)
        if not self.should_compact(total):
            return messages, False  # cheap pre-pass was enough — skip the LLM

        # Phase 3 — LLM autocompact (only when the cheap pass can't get under
        # and the circuit breaker is closed).
        if self._consecutive_compact_failures < _MAX_COMPACT_FAILURES:
            messages = self._sanitize_tool_pairs(await self.autocompact(messages))
            total = self._measure_tokens(messages)
            if self.should_compact(total):
                self._consecutive_compact_failures += 1

        return messages, self.is_at_blocking_limit(total)

    def _is_thrashing(self) -> bool:
        """True when the last two pre-passes each reclaimed < the min saving —
        the cheap wins are exhausted, so re-running just burns cycles."""
        recent = self._recent_savings[-2:]
        return len(recent) == 2 and all(s < _ANTI_THRASH_MIN_SAVING for s in recent)

    # ── Phase 3: LLM autocompact (lossy, full-history summary) ───────────

    async def autocompact(
        self, messages: list[dict], *, keep_last: int = _AUTOCOMPACT_KEEP_LAST
    ) -> list[dict]:
        """Summarize the conversation body into ONE reference-only summary msg.

        Preserves the leading system block + the task-defining user query, then
        replaces the older turns with a single LLM summary, keeping the last
        ``keep_last`` messages verbatim. On LLM failure (or empty summary)
        returns the messages unchanged so the caller's circuit breaker records
        the failure. This is the lossy escape valve used only when the cheap
        pre-pass cannot get under the window — see :meth:`compress`.
        """
        head_end = 0
        while head_end < len(messages) and messages[head_end].get("role") == "system":
            head_end += 1
        # Keep the task-defining user query (first msg after the system block)
        # so the current task is never summarized away.
        if head_end < len(messages) and messages[head_end].get("role") == "user":
            head_end += 1

        body = messages[head_end:]
        if len(body) <= keep_last:
            return messages  # nothing old enough to summarize

        to_summarize = body[:-keep_last]
        tail = body[-keep_last:]
        conversation = "\n\n".join(
            f"{m.get('role', '?')}: {_message_text(m)}" for m in to_summarize
        )

        # ONE summarization function for BOTH the inner (loop-time) and outer
        # (assembly-time) autocompact — same 6-section summary. The loop has no
        # prior summary to fold in here (the existing [Context Summary] lives in
        # the preserved head), so old_summary is empty.
        from app.services.memory.compaction_service import summarize_conversation

        summary = await summarize_conversation("", conversation)
        if not summary:
            return messages  # LLM/parse failure (logged) — caller's breaker counts it

        summary_msg = {
            "role": "system",
            "content": _AUTOCOMPACT_SUMMARY_WRAPPER.format(summary=summary),
        }
        logger.info(
            "autocompact: summarized %d messages → 1 summary + %d kept verbatim",
            len(to_summarize), len(tail),
        )
        return messages[:head_end] + [summary_msg] + tail

    def should_compact(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.cheap_prepass_threshold

    def _measure_tokens(self, messages: list[dict]) -> int:
        """Self-measured prompt size: sum of per-message token estimates.

        Used instead of the API's lagging ``usage.prompt_tokens`` (one LLM call
        behind, and zero on the first iteration) so compaction triggers on the
        message list we are actually about to send.
        """
        return sum(_estimate_message_tokens(m) for m in messages)

    def _prune_old_tool_results(self, messages: list[dict]) -> list[dict]:
        result = list(messages)
        result = self._pass1_dedup(result)
        result = self._pass2_summarize(result)
        result = self._pass3_truncate_args(result)
        result = self._sanitize_tool_pairs(result)
        return result

    # ── Protected-tail boundary (token budget) ───────────────────────

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
            tool_name = self._find_tool_call(messages, msg.get("tool_call_id", ""))[0]
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
                # Skip Stage-A offloaded results: they're recoverable (full
                # bytes on disk) and the <persisted-output> block carries the
                # path the model reads back with. Lossy-summarizing would
                # destroy that path, so leave persisted blocks untouched.
                if (
                    len(content) > _PRUNED_RESULT_MAX_CHARS
                    and not is_persisted_content(content)
                ):
                    tool_name, tool_args = self._find_tool_call(
                        messages, msg.get("tool_call_id", "")
                    )
                    msg = {
                        **msg,
                        "content": _summarize_tool_result(tool_name, tool_args, content),
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

    # ── Reactive compact on context-overflow error ───────────────────

    async def on_context_too_long(
        self,
        messages: list[dict],
    ) -> tuple[list[dict], bool]:
        """Reactive recovery: the LLM call actually returned a context-overflow
        error. The proactive cheap pre-pass already failed, so force an
        aggressive LLM autocompact (keep only the most recent message) and
        signal a single retry. Single-shot per overflow
        (``has_attempted_reactive_compact``) + circuit breaker prevent a death
        spiral. Returns ``(messages, should_retry)``.
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
    def _find_tool_call(messages: list[dict], tool_call_id: str) -> tuple[str, str]:
        """Return ``(tool_name, arguments_json)`` for a tool_call_id.

        Lets Pass-2 summaries describe a result by its actual call arguments
        (query / url / path) rather than guessing from the result body. Falls
        back to ``("unknown", "")`` for orphaned ids.
        """
        if not tool_call_id:
            return "unknown", ""
        for msg in reversed(messages):
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                    fn = tc.get("function", {})
                    return fn.get("name", "unknown"), fn.get("arguments", "") or ""
        return "unknown", ""


__all__ = ["QueryLoopCompactor"]
