"""Google Gemini /v1beta/models adapter (P7-A).

Notable quirks:
  - Auth via ``?key=`` URL query parameter (no header)
  - Response top-level key is ``models``, not ``data``
  - Each entry's id is ``"models/gemini-2.5-flash"`` — we strip the
    ``"models/"`` prefix so what we store matches what the
    /chat/completions endpoint expects.
  - Field name is ``displayName`` (camelCase, not snake_case)
  - Filter uses ``supportedGenerationMethods``: a chat model must
    include ``"generateContent"`` in that array. This is the single
    cleanest non-chat filter of any vendor.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


def _chat_filter(entry: dict, bare_id: str) -> bool:
    # Primary signal: supportedGenerationMethods array. Chat = has
    # generateContent. Drop imagen / veo / lyria / embedding-only /
    # tts-only / image-only entries that don't expose generateContent.
    methods = entry.get("supportedGenerationMethods")
    if isinstance(methods, list) and methods:
        if "generateContent" not in methods:
            return False
    # Defence in depth: drop a few id-namespaced families even when
    # the methods array is missing.
    lower = bare_id.lower()
    if any(hint in lower for hint in (
        "imagen", "veo", "lyria", "nano-banana",
        "embedding", "aqa",
        "tts", "text-to-speech",
        "robotics-er",          # gemini-robotics-er-* — robotics-only
        "antigravity",          # antigravity-preview — agent-only sandbox
        "deep-research",        # deep-research-* — async research wrapper
        "computer-use",
        "native-audio",         # gemini-*-native-audio-* — audio API
        "image-preview",        # gemini-3.5-flash-image / image-preview
    )):
        return False
    return True


SPEC = VendorAdapterSpec(
    provider="gemini",
    models_path="/models",          # api_base already includes /v1beta/openai → we strip in pipeline below
    auth_style="url-key",
    response_top_key="models",
    id_field="name",
    display_name_field="displayName",
    context_window_field="inputTokenLimit",
    max_output_field="outputTokenLimit",
    strip_id_prefix="models/",
    chat_filter=_chat_filter,
    fallback_context_window=1_000_000,
    fallback_max_output=8_192,
    fallback_supports_function_calling=True,
)


# NOTE on api_base: PROVIDERS['gemini'].default_api_base points at
# ``generativelanguage.googleapis.com/v1beta/openai`` — that's the
# OpenAI-compatible chat-completions endpoint. The list-models
# endpoint lives one level up at ``/v1beta/models``. The pipeline
# special-cases this single override (see pipeline.py) rather than
# bloating the spec with an api_base_override field nobody else
# would use.
