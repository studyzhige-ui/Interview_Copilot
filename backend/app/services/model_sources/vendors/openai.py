"""OpenAI /v1/models adapter (P7-A)."""
from __future__ import annotations

from .base import VendorAdapterSpec


# OpenAI's /v1/models returns ALL models the org has access to —
# chat + embedding + image + audio + tts + realtime + search-api etc.
# This filter keeps only the chat-family ids. The list of "non-chat"
# hints comes from inspecting the live response (see verification
# script output in P7-A).
_NON_CHAT_HINTS = (
    "embed", "embedding",
    "whisper", "tts", "audio",
    "dall-e", "image", "moderation",
    "realtime",                    # gpt-realtime-* — websocket audio API
    "search-api",                  # gpt-5.5-search-api etc — search wrapper
    "gpt-image",
    "computer-use",                # computer-use-preview — agent-only
)


def _chat_filter(entry: dict, bare_id: str) -> bool:
    lower = bare_id.lower()
    if any(hint in lower for hint in _NON_CHAT_HINTS):
        return False
    # Drop bare placeholders like "chat-latest" without a vendor prefix.
    if lower == "chat-latest":
        return False
    return True


SPEC = VendorAdapterSpec(
    provider="openai",
    models_path="/models",          # api_base already includes /v1
    auth_style="bearer",
    created_int_field="created",
    chat_filter=_chat_filter,
    fallback_context_window=128_000,
    fallback_max_output=16_384,
    fallback_supports_function_calling=True,
)
