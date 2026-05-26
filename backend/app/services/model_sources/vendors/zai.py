"""Zhipu GLM (z.ai) /api/paas/v4/models adapter (P7-A).

Zhipu BigModel uses the z.ai brand internationally. Their OpenAI-
compatible endpoint at ``open.bigmodel.cn/api/paas/v4`` exposes a
``/models`` GET returning the GLM family (glm-4.5 / glm-4.6 /
glm-5 etc) with ``created`` unix timestamps.

All entries returned are chat models — no filter needed.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


SPEC = VendorAdapterSpec(
    provider="zai",
    models_path="/models",          # api_base = open.bigmodel.cn/api/paas/v4
    auth_style="bearer",
    created_int_field="created",
    chat_filter=None,
    fallback_context_window=128_000,
    fallback_max_output=8_192,
    fallback_supports_function_calling=True,
)
