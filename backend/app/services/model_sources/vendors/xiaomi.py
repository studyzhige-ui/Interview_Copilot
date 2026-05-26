"""Xiaomi MiMo /v1/models adapter (P7-A).

Xiaomi's API is OpenAI-compatible at ``api.xiaomimimo.com/v1``. The
live verification (P7-A) returned 9 entries — 6 chat (mimo-v2-* /
mimo-v2.5-* family) + 3 TTS variants we need to filter out.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


def _chat_filter(entry: dict, bare_id: str) -> bool:
    lower = bare_id.lower()
    # Drop TTS / voice / embedding / image variants. The mimo-v2.5-tts
    # family ships voice-clone / voice-design endpoints that aren't
    # chat-completion compatible.
    if any(hint in lower for hint in (
        "tts", "voice", "embedding", "embed-",
        "image", "img-", "video",
    )):
        return False
    return True


SPEC = VendorAdapterSpec(
    provider="xiaomi",
    models_path="/models",
    auth_style="bearer",
    chat_filter=_chat_filter,
    fallback_context_window=1_000_000,
    fallback_max_output=8_192,
    fallback_supports_function_calling=True,
)
