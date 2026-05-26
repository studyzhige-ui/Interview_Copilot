"""NVIDIA NIM /v1/models adapter (P7-A).

NIM is a model catalog for *every* model NVIDIA hosts — text, vision,
embeddings, safety classifiers, RAG retrievers, OCR/parse, TTS,
video detectors, etc. The /v1/models endpoint returns 100+ entries,
the vast majority of which are NOT chat models.

The ``created`` field NVIDIA ships is a fixed sentinel
(``735790403`` = 1993-04-26) for every entry — useless for sorting.
base.py's _coerce_timestamp already drops anything older than
2020-01-01 to avoid being misled by this.

Heavy chat-only filtering is required.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


# Substring-based blocklist for non-chat NIM entries. Designed from
# inspecting the live response — see P7-A verification output (123
# entries, ~60% are non-chat).
_NON_CHAT_HINTS = (
    # Embeddings
    "/embed", "-embed-", "embedqa", "/nv-embed",
    # Safety / guard / topic-control
    "guard", "safety", "topic-control",
    "content-safety", "topic_control",
    # OCR / parse / retriever
    "nemoretriever", "retriever",
    "nemotron-parse", "/parse",
    # Speech / translate
    "riva-", "asr-", "tts-",
    # Vision-only / image
    "nvclip", "vila", "neva-", "kosmos", "fuyu", "deplot",
    "synthetic-video-detector",
    # Reward models (training only)
    "reward",
    # Domain-specific non-chat
    "gliner", "gemma-3n-",       # tiny inference models
)


def _chat_filter(entry: dict, bare_id: str) -> bool:
    lower = bare_id.lower()
    if any(hint in lower for hint in _NON_CHAT_HINTS):
        return False
    return True


SPEC = VendorAdapterSpec(
    provider="nvidia_nim",
    models_path="/models",          # api_base = integrate.api.nvidia.com/v1
    auth_style="bearer",
    created_int_field="created",    # all sentinel; _coerce_timestamp drops it
    chat_filter=_chat_filter,
    fallback_context_window=128_000,
    fallback_max_output=4_096,
    fallback_supports_function_calling=False,  # NIM-hosted OSS models often don't
)
