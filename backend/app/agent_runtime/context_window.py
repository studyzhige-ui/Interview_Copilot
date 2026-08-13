"""Model-aware context window calculations for the Agent Harness.

Centralizes token-budget arithmetic so that the active-Turn reducer
and agent loop never hardcode model-specific constants.

Design reference:
  - Claude Code ``calculateTokenWarningState`` (query.ts L634):
        effectiveWindow = contextWindow - min(maxOutputTokens, 20_000)
        blockingLimit   = effectiveWindow - 3_000
  - Pressure threshold (a conservative provider-neutral default):
        cheap_prepass_threshold = effectiveWindow - 13_000

All functions are pure — no side effects, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.model_catalog import ModelProfile

# ── Conservative defaults ────────────────────────────────────────────────

# Maximum output token reservation when computing effective window.
_MAX_OUTPUT_RESERVE = 20_000

# Token Warning blocking buffer — refuse LLM call when this close to limit.
_BLOCKING_BUFFER = 3_000

# Start replacing durable ToolResult payloads with identity references before
# the blocking limit.  This is a model-profile fallback, not a claim that all
# providers share Claude's internal constants.
_CHEAP_PREPASS_BUFFER = 13_000


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
    """Token count at which pressure-only ToolResult reduction may start."""
    return get_effective_window(profile) - _CHEAP_PREPASS_BUFFER
