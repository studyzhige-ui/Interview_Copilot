"""Agent-loop-level context compaction for the messages list.

This is NOT the transcript-level ``CompactionService`` (which summarises
conversation history across turns).  This module handles the *messages*
array inside a single ``run_react_agent`` invocation — when tool calls
pile up, old tool results are pruned to stay within the context window.

Design reference: Hermes Agent ``context_compressor.py`` — the pre-pass
``_prune_old_tool_results`` strategy.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Threshold ratio — compact when prompt_tokens exceed this fraction of the
# model context window.
_COMPACT_THRESHOLD_RATIO = 0.65
_MODEL_CONTEXT_WINDOW = 128_000  # conservative estimate

# Number of most-recent tool-result messages to protect from pruning.
_PROTECT_TAIL_TOOL_RESULTS = 4

# Maximum chars kept per pruned tool result.
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


class AgentContextCompactor:
    """Prunes old tool results from the agent messages list.

    Strategy:
      1. Never touch system messages (head protection).
      2. Protect the most recent N tool-result messages (tail protection).
      3. Replace older tool-result contents with informational summaries.
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

    def should_compact(self, prompt_tokens: int) -> bool:
        return prompt_tokens >= self.threshold_tokens

    def prune_old_tool_results(self, messages: list[dict]) -> list[dict]:
        """Return a new messages list with old tool results pruned."""
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
