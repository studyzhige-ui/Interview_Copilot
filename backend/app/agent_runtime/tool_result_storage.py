"""Stage A — offload oversized tool results instead of truncating them.

When a tool result is too large to keep inline, the full output is written to
local storage and the in-context copy is replaced with a short preview + the
file path; the model reads the rest on demand via ``read_file`` (itself never
offloaded, to avoid a persist→read loop). Unlike the lossy Phase-1 summaries,
this is recoverable — the full bytes stay on disk.

Three levels of defense against context-window overflow:

1. **Per-tool output cap** (``ToolEntry.max_result_chars``): the registry
   truncates at this level, but the per-result step below can override it.

2. **Per-result persistence** (``maybe_persist_result``): if a single result
   exceeds ``AGENT_PERSIST_THRESHOLD``, write the full content to
   ``{APP_DATA_DIR}/agent-results/{session_id}/{tool_call_id}.txt`` and replace
   the in-context content with a preview + path (read back via
   ``resolve_persisted_path`` + ``read_file``).

3. **Per-turn aggregate budget** (``enforce_turn_budget``): if all tool
   results in one assistant turn together exceed ``AGENT_TURN_BUDGET_CHARS``,
   spill the largest non-persisted results until under budget — catching many
   medium results that combine to overflow.
"""

import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# XML-style tags marking a persisted-output block in the message stream.
PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"

# Tools whose output is never offloaded (would create a persist→read loop).
_NEVER_PERSIST_TOOLS: frozenset[str] = frozenset({"read_file"})


# ── Storage directory helpers ────────────────────────────────────────────

def _storage_dir(session_id: str) -> Path:
    """Return the local directory for persisted tool results."""
    return Path(settings.APP_DATA_DIR) / "agent-results" / session_id


def _ensure_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


# ── Preview generation ───────────────────────────────────────────────────

def generate_preview(content: str, max_chars: int | None = None) -> tuple[str, bool]:
    """Truncate at last newline within *max_chars*.  Returns (preview, has_more).

    Mirrors Hermes ``generate_preview``: prefers cutting at a newline
    boundary to avoid mid-line splits.
    """
    max_chars = max_chars or settings.AGENT_PERSIST_PREVIEW_SIZE
    if len(content) <= max_chars:
        return content, False
    truncated = content[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[: last_nl + 1]
    return truncated, True


def _build_persisted_message(
    preview: str,
    has_more: bool,
    original_size: int,
    file_path: str,
) -> str:
    """Build the ``<persisted-output>`` replacement block.

    Matches the Hermes/Claude Code format so the model knows:
      - The result was too large and was saved
      - Where to find the full output
      - A preview of the first N chars
    """
    size_kb = original_size / 1024
    if size_kb >= 1024:
        size_str = f"{size_kb / 1024:.1f} MB"
    else:
        size_str = f"{size_kb:.1f} KB"

    msg = f"{PERSISTED_OUTPUT_TAG}\n"
    msg += f"This tool result was too large ({original_size:,} characters, {size_str}).\n"
    msg += f"Full output saved to: {file_path}\n"
    msg += "Use the read_file tool with the path above to access specific sections.\n\n"
    msg += f"Preview (first {len(preview)} chars):\n"
    msg += preview
    if has_more:
        msg += "\n..."
    msg += f"\n{PERSISTED_OUTPUT_CLOSING_TAG}"
    return msg


# ── Per-result persistence ───────────────────────────────────────────────

def resolve_threshold(tool_name: str) -> int | float:
    """Resolve the effective persistence threshold for a tool.

    - Tools in ``_NEVER_PERSIST_TOOLS`` → ``inf`` (never persisted).
    - Otherwise → ``settings.AGENT_PERSIST_THRESHOLD``.
    """
    if tool_name in _NEVER_PERSIST_TOOLS:
        return float("inf")
    return settings.AGENT_PERSIST_THRESHOLD


def maybe_persist_result(
    content: str,
    tool_name: str,
    tool_call_id: str,
    session_id: str,
    *,
    threshold: int | float | None = None,
) -> str:
    """Persist an oversized tool result to local storage.

    If the content exceeds the threshold, write it to disk and return
    a ``<persisted-output>`` replacement with a preview and file path.
    Otherwise, return the content unchanged.

    Falls back to inline truncation if the write fails.
    """
    effective_threshold = threshold if threshold is not None else resolve_threshold(tool_name)

    # inf threshold → never persist (read_file protection)
    if effective_threshold == float("inf"):
        return content

    if len(content) <= effective_threshold:
        return content

    # Persist to local storage
    storage = _storage_dir(session_id)
    file_path = storage / f"{tool_call_id}.txt"
    preview, has_more = generate_preview(content)

    try:
        _ensure_dir(storage)
        file_path.write_text(content, encoding="utf-8")
        logger.info(
            "Persisted large tool result: %s (%s, %d chars -> %s)",
            tool_name, tool_call_id, len(content), file_path,
        )
        return _build_persisted_message(preview, has_more, len(content), str(file_path))
    except Exception as exc:
        logger.warning("Failed to persist tool result %s: %s", tool_call_id, exc)
        # Fallback: inline truncation with a notice
        return (
            f"{preview}\n\n"
            f"[Truncated: tool response was {len(content):,} chars. "
            f"Full output could not be saved to storage.]"
        )


# ── Per-turn aggregate budget ────────────────────────────────────────────

def enforce_turn_budget(
    tool_messages: list[dict],
    session_id: str,
) -> list[dict]:
    """Enforce the aggregate character budget across all tool results in a turn.

    If total chars exceed ``AGENT_TURN_BUDGET_CHARS``, persist the
    largest non-persisted results first until under budget.

    Already-persisted results (containing ``PERSISTED_OUTPUT_TAG``) are
    skipped.  Mutates the list in-place and returns it.
    """
    budget = settings.AGENT_TURN_BUDGET_CHARS

    # Collect candidates: non-persisted tool messages with their sizes
    candidates: list[tuple[int, int]] = []  # (index, size)
    total_size = 0
    for i, msg in enumerate(tool_messages):
        content = msg.get("content", "")
        size = len(content)
        total_size += size
        if PERSISTED_OUTPUT_TAG not in content:
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
        tool_call_id = msg.get("tool_call_id", f"budget_{idx}")

        replacement = maybe_persist_result(
            content=content,
            tool_name="__budget_enforcement__",
            tool_call_id=tool_call_id,
            session_id=session_id,
            threshold=0,  # force persistence
        )
        if replacement != content:
            total_size -= size
            total_size += len(replacement)
            tool_messages[idx] = {**msg, "content": replacement}
            logger.info(
                "Budget enforcement: persisted tool result %s (%d chars)",
                tool_call_id, size,
            )

    return tool_messages


def is_persisted_content(content: str) -> bool:
    """Check if content has already been replaced by a persisted-output block."""
    return content.startswith(PERSISTED_OUTPUT_TAG)


def resolve_persisted_path(session_id: str, path_str: str) -> Path | None:
    """Resolve *path_str* to a persisted-result file confined to *session_id*.

    Read-back companion to :func:`maybe_persist_result`. Returns the resolved
    path only when it lives inside this session's ``agent-results`` directory
    and is an existing file — otherwise ``None``. Both sides are resolved to
    absolute paths and checked with ``relative_to``, which blocks path
    traversal, so a tool can only read back files this session actually
    persisted (never arbitrary disk locations).
    """
    if not path_str:
        return None
    base = _storage_dir(session_id).resolve()
    try:
        target = Path(path_str).resolve()
        target.relative_to(base)
    except (ValueError, OSError):
        return None
    return target if target.is_file() else None
