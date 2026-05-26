"""DeepSeek /models adapter (P7-A).

Cleanest possible response — DeepSeek's /v1/models returns just the
chat models (``deepseek-v4-flash`` + ``deepseek-v4-pro`` as of
P7-A live verification). No timestamps, no display names. We add
fallback metadata from the V4 announcement (1M context, 16K output).

The ``deepseek-chat`` / ``deepseek-reasoner`` aliases were
deprecated 2026-07-24 and removed from the /v1/models response;
DeepSeek itself confirms V4 is the truth.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


SPEC = VendorAdapterSpec(
    provider="deepseek",
    models_path="/models",
    auth_style="bearer",
    # Response is already chat-only — no filter needed.
    chat_filter=None,
    fallback_context_window=1_000_000,       # V4 ships 1M context
    fallback_max_output=16_384,
    fallback_supports_function_calling=True,
)
