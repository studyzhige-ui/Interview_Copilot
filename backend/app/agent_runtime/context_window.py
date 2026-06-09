"""Model-aware context window calculations for the Agent Harness.

Centralizes all token-budget arithmetic so that the QueryLoopCompactor
and agent loop never hardcode model-specific constants.

Design reference:
  - Claude Code ``calculateTokenWarningState`` (query.ts L634):
        effectiveWindow = contextWindow - min(maxOutputTokens, 20_000)
        blockingLimit   = effectiveWindow - 3_000
  - Cheap pre-pass threshold (mirrors Claude Code's autocompact buffer):
        cheap_prepass_threshold = effectiveWindow - 13_000

All functions are pure — no side effects, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.model_registry import ModelProfile

# ── Buffer constants (Claude Code values) ────────────────────────────────

# Maximum output token reservation when computing effective window.
_MAX_OUTPUT_RESERVE = 20_000

# Token Warning blocking buffer — refuse LLM call when this close to limit.
_BLOCKING_BUFFER = 3_000

# Cheap pre-pass trigger buffer — begin the zero-LLM dedup/summarize/truncate
# pre-pass at this margin below the effective window. (Claude Code's value for
# its autocompact buffer; kept configurable. NOT the LLM-summary trigger.)
_CHEAP_PREPASS_BUFFER = 13_000

# Tail protection: minimum token budget reserved for recent tool results
# that should never be pruned.  Replaces old fixed-count protection.
TAIL_BUDGET_TOKENS = 4_000


def get_effective_window(profile: ModelProfile) -> int:
    """Usable context window after reserving output tokens.

    Claude Code formula: contextWindow - min(maxOutputTokens, 20_000).
    This prevents the output reservation from eating into the entire
    context for models that advertise very large output windows.
    """
    output_reserve = min(profile.max_output_tokens, _MAX_OUTPUT_RESERVE)
    return profile.context_window - output_reserve


def get_blocking_limit(profile: ModelProfile) -> int:
    """Token count at which the agent loop must STOP rather than call LLM.

    Claude Code ``isAtBlockingLimit``: effective - 3_000.
    When prompt_tokens >= this value, any LLM call is doomed to fail.
    """
    return get_effective_window(profile) - _BLOCKING_BUFFER


def get_cheap_prepass_threshold(profile: ModelProfile) -> int:
    """Token count at which the cheap, zero-LLM pre-pass should activate.

    Mirrors Claude Code's autocompact buffer (effective - 13_000), but this
    gates the cheap dedup/summarize/truncate pre-pass — NOT the LLM
    summarization phase (the codebase reserves "autocompact" for that).
    Below this threshold, pruning is skipped for performance.
    """
    return get_effective_window(profile) - _CHEAP_PREPASS_BUFFER
