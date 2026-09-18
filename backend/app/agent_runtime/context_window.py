"""Model-aware context limits backed by the shared request budget."""

from __future__ import annotations
from typing import TYPE_CHECKING
from app.core.context_budget import RequestBudget

if TYPE_CHECKING:
    from app.core.model_catalog import ModelProfile


def get_effective_window(profile: ModelProfile) -> int:
    return max(0, profile.context_window - profile.max_output_tokens)


def get_blocking_limit(profile: ModelProfile) -> int:
    return RequestBudget.resolve(
        profile.context_window, profile.max_output_tokens
    ).input_limit


def get_cheap_prepass_threshold(profile: ModelProfile) -> int:
    return RequestBudget.resolve(
        profile.context_window, profile.max_output_tokens
    ).compact_at
