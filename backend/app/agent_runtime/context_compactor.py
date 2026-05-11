"""3-layer context management pipeline for the Agent Harness.

Design reference:
  - Claude Code: snip → microcompact → autocompact → reactive compact
  - Hermes: ContextCompressor.maybe_compress() + tool_result_storage

Our 3-layer adaptation:

  Layer 1 (pre-LLM): Tool result persistence & turn budget enforcement.
    Handled by ``tool_result_storage`` module — O(N) char comparison,
    no LLM call.  Already applied in the main loop before messages are
    appended.

  Layer 2 (pre-LLM): Old tool result summarization.
    When prompt_tokens approach the context window threshold, replace
    old tool results (outside the protected tail) with structured
    summaries.  O(N) string replacement, no LLM call.

  Layer 3 (post-LLM): Reactive compact on context_too_long error.
    If the API returns a context-length error, compress aggressively
    and retry.  ``has_attempted_reactive_compact`` flag prevents
    infinite loops (Claude Code ``hasAttemptedReactiveCompact`` pattern).
    Budget step is refunded on compression-retry (Hermes L12974 pattern).

This replaces the old ``AgentContextCompactor`` which was a single-layer
design.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Threshold ratio — compact when prompt_tokens exceed this fraction of the
# model context window.
_COMPACT_THRESHOLD_RATIO = 0.65
_MODEL_CONTEXT_WINDOW = 1_000_000  # DeepSeek V4 Pro/Flash: 1M tokens

# Number of most-recent tool-result messages to protect from pruning.
_PROTECT_TAIL_TOOL_RESULTS = 4

# Maximum chars kept per pruned tool result summary.
_PRUNED_RESULT_MAX_CHARS = 200


def _summarize_tool_result(tool_name: str, content: str) -> str:
    """Create a short informational summary of a tool result.

    This mirrors the Hermes ``_summarize_tool_result`` approach: instead
    of blindly truncating, produce a tiny structured summary so the LLM
    still knows *what happened* without the full payload.
    """
    char_count = len(content)
    line_count = content.count("\n") + 1

    # Try to extract a meaningful first line
    first_line = content.split("\n", 1)[0].strip()[:120]

    # Try to detect JSON result shapes
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


class ContextPipeline:
    """3-layer context management pipeline.

    Layer 1: tool result persistence (pre-LLM, handled externally)
    Layer 2: old result summarization (pre-LLM, ``pre_llm_compact``)
    Layer 3: reactive compact on 413 (post-LLM, ``on_context_too_long``)
    """

    def __init__(
        self,
        *,
        threshold_ratio: float = _COMPACT_THRESHOLD_RATIO,
        context_window: int = _MODEL_CONTEXT_WINDOW,
        protect_tail: int = _PROTECT_TAIL_TOOL_RESULTS,
    ):
        self.threshold_tokens = int(context_window * threshold_ratio)
        self.protect_tail = protect_tail
        # Claude Code pattern: prevent infinite reactive-compact loops
        self.has_attempted_reactive_compact: bool = False

    # ── Layer 2: Pre-LLM old result summarization ────────────────────

    def should_compact(self, prompt_tokens: int) -> bool:
        """Check if prompt_tokens exceed the compaction threshold."""
        return prompt_tokens >= self.threshold_tokens

    def pre_llm_compact(self, messages: list[dict], prompt_tokens: int) -> list[dict]:
        """Layer 2: summarize old tool results if approaching context limit.

        Called after each tool batch, before the next LLM call.  Only
        activates when prompt_tokens exceed the threshold.
        """
        if not self.should_compact(prompt_tokens):
            return messages
        return self._prune_old_tool_results(messages)

    def _prune_old_tool_results(self, messages: list[dict]) -> list[dict]:
        """Replace old tool-result contents with informational summaries.

        Strategy:
          1. Never touch system messages (head protection).
          2. Protect the most recent N tool-result messages (tail protection).
          3. Replace older tool-result contents with structured summaries.
        """
        # Find indices of all tool-result messages
        tool_indices = [
            i for i, m in enumerate(messages)
            if m.get("role") == "tool"
        ]
        if len(tool_indices) <= self.protect_tail:
            return messages  # nothing to prune

        # Indices to prune (all except the most recent N)
        prune_set = set(tool_indices[: -self.protect_tail])

        pruned = []
        pruned_count = 0
        for i, msg in enumerate(messages):
            if i in prune_set:
                content = msg.get("content", "")
                if len(content) > _PRUNED_RESULT_MAX_CHARS:
                    # Find tool name from the preceding assistant message
                    tool_name = self._find_tool_name(messages, msg.get("tool_call_id", ""))
                    msg = {
                        **msg,
                        "content": _summarize_tool_result(tool_name, content),
                    }
                    pruned_count += 1
            pruned.append(msg)

        if pruned_count > 0:
            logger.info(
                "Context compaction: pruned %d old tool results (%d protected)",
                pruned_count,
                self.protect_tail,
            )
        return pruned

    # ── Layer 3: Reactive compact on context_too_long ────────────────

    def on_context_too_long(
        self,
        messages: list[dict],
    ) -> tuple[list[dict], bool]:
        """Layer 3: emergency compression when API returns context_too_long.

        Returns (messages, should_retry).

        ``has_attempted_reactive_compact`` prevents infinite loops:
        if we already tried compressing and it's still too long,
        return False to let the error propagate.

        Design reference:
          - Claude Code ``hasAttemptedReactiveCompact`` (query.ts:1157)
          - Hermes compression-retry refund (run_agent.py:12974)
        """
        if self.has_attempted_reactive_compact:
            logger.warning(
                "Reactive compact already attempted — refusing retry to prevent loop"
            )
            return messages, False

        self.has_attempted_reactive_compact = True
        messages = self._prune_old_tool_results(messages)
        logger.info("Reactive compact applied — will retry LLM call")
        return messages, True

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

