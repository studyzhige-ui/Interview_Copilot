"""Moonshot Kimi /v1/models adapter (P7-A).

Moonshot ships a rich entry shape: ``created`` (unix int), plus per-
model ``supports_*`` flags. Live verification returned 9 entries
including ``kimi-k2.6`` (latest) and ``moonshot-v1-*-vision-preview``.
All chat — no filter needed.
"""
from __future__ import annotations

from .base import VendorAdapterSpec


SPEC = VendorAdapterSpec(
    provider="moonshot",
    models_path="/models",
    auth_style="bearer",
    created_int_field="created",
    chat_filter=None,
    fallback_context_window=128_000,
    fallback_max_output=4_096,
    fallback_supports_function_calling=True,
)
