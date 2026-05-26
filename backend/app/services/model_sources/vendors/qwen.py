"""Qwen / DashScope (Alibaba) /v1/models adapter (P7-A).

DashScope's OpenAI-compatible endpoint returns 247+ entries — heavily
polluted with third-party gateway models (ZHIPU/GLM-5, deepseek-*,
mistral-*, llama3-*, baichuan-*, moonshot-* etc owned_by="system").
We keep ONLY Qwen-family entries to avoid surfacing the same model
via multiple vendor cards (the user with a Zhipu key sees GLM via
zai card; surfacing GLM via the qwen card would be confusing).

Filter strategy: keep ids that start with ``qwen`` or ``qwq`` (Qwen
brand prefixes); drop everything else. Also drop embedding / audio /
image / video / TTS variants of Qwen itself.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


_QWEN_PREFIXES = ("qwen", "qwq")
_NON_CHAT_HINTS = (
    "embedding", "embed-", "rerank", "reranker",
    "asr", "tts", "audio",
    "image", "img", "vl-image", "wanx",      # wanx = Aliyun image gen
    "video",
    "math-",                                  # qwen-math-* — specialty models, not general chat
    "moe-",                                   # qwen-moe-* — research / not general use
)


def _chat_filter(entry: dict, bare_id: str) -> bool:
    lower = bare_id.lower()
    # 1) Only Qwen brand. Third-party gateway models live under
    #    other vendor cards if the user enables them.
    if not any(lower.startswith(p) for p in _QWEN_PREFIXES):
        return False
    # 2) Drop non-chat Qwen variants.
    if any(hint in lower for hint in _NON_CHAT_HINTS):
        return False
    return True


SPEC = VendorAdapterSpec(
    provider="qwen",
    models_path="/models",      # api_base = dashscope.aliyuncs.com/compatible-mode/v1
    auth_style="bearer",
    created_int_field="created",
    chat_filter=_chat_filter,
    fallback_context_window=128_000,
    fallback_max_output=8_192,
    fallback_supports_function_calling=True,
)
