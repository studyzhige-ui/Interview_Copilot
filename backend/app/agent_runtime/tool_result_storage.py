"""Bound model-visible Tool results without creating a second result store.

``AgentToolCall.result_json`` is the canonical, durable, redacted Tool result.
When that result is too large for the model context, this module replaces only
the model-visible copy with a preview plus the exact Tool Call identity. The
model can page the canonical row through ``read_file(tool_call_id=...)`` on any
worker after a retry or restart.

Three levels of defense against context-window overflow:

1. **Per-tool output cap** (``ToolDefinition.max_result_chars``): enforced here
   in ``resolve_threshold`` — a result larger than the tool's registered cap
   is projected (recoverable), not destroyed. The effective threshold is
   ``min(max_result_chars, AGENT_RESULT_INLINE_THRESHOLD)``.

2. **Per-result projection** (``project_oversized_result``): if a single result
   exceeds the effective threshold, replace the in-context content with a
   preview + ``tool_call_id``. No local file or duplicate durable owner exists.

3. **Per-turn aggregate budget** (``enforce_turn_budget``): if all tool
   results in one assistant turn together exceed ``AGENT_TURN_BUDGET_CHARS``,
   project the largest inline results until under budget — catching many
   medium results that combine to overflow.
"""

import logging

from app.agent_runtime.tool_redaction import redact_tool_text
from app.core.config import settings

logger = logging.getLogger(__name__)

# XML-style tags marking a durable Tool-result reference in model context.
TOOL_RESULT_REFERENCE_TAG = "<tool-result-reference>"
TOOL_RESULT_REFERENCE_CLOSING_TAG = "</tool-result-reference>"

# A paged read must stay inline or it could recursively point at itself.
_NEVER_PROJECT_TOOLS: frozenset[str] = frozenset({"read_file"})


# ── Preview generation ───────────────────────────────────────────────────


def generate_preview(content: str, max_chars: int | None = None) -> tuple[str, bool]:
    """Truncate at last newline within *max_chars*.  Returns (preview, has_more).

    Mirrors Hermes ``generate_preview``: prefers cutting at a newline
    boundary to avoid mid-line splits.
    """
    max_chars = max_chars or settings.AGENT_RESULT_PREVIEW_SIZE
    if len(content) <= max_chars:
        return content, False
    truncated = content[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[: last_nl + 1]
    return truncated, True


def _build_result_reference(
    preview: str,
    has_more: bool,
    original_size: int,
    tool_call_id: str,
) -> str:
    """Build a bounded pointer to the canonical ``AgentToolCall`` result."""
    size_kb = original_size / 1024
    if size_kb >= 1024:
        size_str = f"{size_kb / 1024:.1f} MB"
    else:
        size_str = f"{size_kb:.1f} KB"

    msg = f"{TOOL_RESULT_REFERENCE_TAG}\n"
    msg += (
        f"This tool result was too large ({original_size:,} characters, {size_str}).\n"
    )
    msg += f"Canonical tool_call_id: {tool_call_id}\n"
    msg += (
        "Use read_file with this tool_call_id and offset/limit to page the "
        "full durable result.\n\n"
    )
    msg += f"Preview (first {len(preview)} chars):\n"
    msg += preview
    if has_more:
        msg += "\n..."
    msg += f"\n{TOOL_RESULT_REFERENCE_CLOSING_TAG}"
    return msg


# ── Per-result persistence ───────────────────────────────────────────────


def resolve_threshold(tool_name: str) -> int | float:
    """Resolve the effective model-projection threshold for a tool.

    - Tools in ``_NEVER_PROJECT_TOOLS`` → ``inf`` (never projected).
    - Otherwise → ``min(ToolDefinition.max_result_chars, AGENT_RESULT_INLINE_THRESHOLD)``.
      This is what makes the per-tool cap real: a tool registered with a
      2K cap gets its oversized result projected at 2K instead of riding
      the global 50K default into the LLM context and the SSE frame.
    """
    if tool_name in _NEVER_PROJECT_TOOLS:
        return float("inf")
    threshold: int | float = settings.AGENT_RESULT_INLINE_THRESHOLD
    try:
        # Lazy import: registry ← tools ← (this module, via read_file) —
        # importing at module level would risk a cycle through file_tool.
        from app.agent_runtime.tool_registry import registry

        entry = registry.get(tool_name)
        if entry is not None and entry.max_result_chars > 0:
            threshold = min(threshold, entry.max_result_chars)
    except Exception:  # noqa: BLE001 — unknown tool → global default
        pass
    return threshold


def project_oversized_result(
    content: str,
    tool_name: str,
    tool_call_id: str,
    *,
    threshold: int | float | None = None,
) -> str:
    """Return a bounded model projection for an oversized durable result."""
    # Defense in depth: callers should already pass the execution-boundary
    # projection, but overflow storage must never become a raw-secret bypass.
    content = redact_tool_text(content)
    effective_threshold = (
        threshold if threshold is not None else resolve_threshold(tool_name)
    )

    # inf threshold → never project (read_file recursion protection)
    if effective_threshold == float("inf"):
        return content

    if len(content) <= effective_threshold:
        return content

    preview, has_more = generate_preview(content)
    logger.info(
        "Projected oversized Tool result from canonical call: %s (%s, %d chars)",
        tool_name,
        tool_call_id,
        len(content),
    )
    return _build_result_reference(preview, has_more, len(content), tool_call_id)


# ── Per-turn aggregate budget ────────────────────────────────────────────


def enforce_turn_budget(tool_messages: list[dict]) -> list[dict]:
    """Enforce the aggregate character budget across all tool results in a turn.

    If total chars exceed ``AGENT_TURN_BUDGET_CHARS``, project the largest
    inline results first until under budget.

    Existing result references are
    skipped.  Mutates the list in-place and returns it.
    """
    budget = settings.AGENT_TURN_BUDGET_CHARS

    # Collect candidates: inline tool messages with their sizes.
    candidates: list[tuple[int, int]] = []  # (index, size)
    total_size = 0
    for i, msg in enumerate(tool_messages):
        content = redact_tool_text(str(msg.get("content", "")))
        msg["content"] = content
        size = len(content)
        total_size += size
        if TOOL_RESULT_REFERENCE_TAG not in content:
            candidates.append((i, size))

    if total_size <= budget:
        return tool_messages

    # Sort candidates by size descending — spill the largest first
    candidates.sort(key=lambda x: x[1], reverse=True)

    for idx, size in candidates:
        if total_size <= budget:
            break

        msg = tool_messages[idx]
        content = msg["content"]
        tool_call_id = str(msg.get("tool_call_id") or "").strip()
        if not tool_call_id:
            raise ValueError("Tool result is missing its canonical tool_call_id")

        replacement = project_oversized_result(
            content=content,
            tool_name="__budget_enforcement__",
            tool_call_id=tool_call_id,
            threshold=0,  # force projection
        )
        if replacement != content:
            total_size -= size
            total_size += len(replacement)
            # Mutate the dict IN PLACE — the caller's ``messages`` list (the
            # actual LLM context) holds references to these same dicts, so
            # replacing the list slot with a copy would leave the oversized
            # content in context and make this whole pass a no-op.
            msg["content"] = replacement
            logger.info(
                "Budget enforcement: projected Tool result %s (%d chars)",
                tool_call_id,
                size,
            )

    return tool_messages


def is_result_reference(content: str) -> bool:
    """Return whether model content points to a canonical Tool result."""
    return content.startswith(TOOL_RESULT_REFERENCE_TAG)
