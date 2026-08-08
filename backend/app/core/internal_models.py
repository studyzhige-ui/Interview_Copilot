"""Platform-owned models for routing and background work."""

from __future__ import annotations

from app.core import model_catalog
from app.core.config import settings
from app.core.model_catalog import ModelProfile
from app.services.model_sources.providers import get_provider_defaults

INTERNAL_MODEL_ROLES: tuple[str, ...] = ("router", "worker")


def get_internal_model_profile(role: str) -> ModelProfile:
    """Resolve an internal role without consulting user settings or keys."""
    if role not in INTERNAL_MODEL_ROLES:
        raise ValueError(f"Unknown internal model role: {role}")

    provider_id = settings.INTERNAL_LLM_PROVIDER.strip()
    model = settings.INTERNAL_LLM_MODEL.strip()
    provider = get_provider_defaults(provider_id)
    if provider is None:
        raise ValueError(f"Unknown internal LLM provider: {provider_id}")
    if not model:
        raise ValueError("INTERNAL_LLM_MODEL must not be empty")

    profile_id = f"{provider_id}/{model}"
    discovered = model_catalog._get_all_profiles().get(profile_id)
    if discovered is not None:
        return discovered

    # Internal availability must not depend on a successful /models refresh.
    # The deployment explicitly selected this model, so construct the same
    # runtime profile from provider-level metadata when the catalog is cold.
    return ModelProfile(
        id=profile_id,
        provider=provider_id,
        display_name=model,
        model=model,
        api_base=provider.default_api_base,
        api_key_env=provider.api_key_env,
        supports_function_calling=False,
        description="Platform-managed internal model",
        context_window=1_000_000 if provider_id == "deepseek" else 128_000,
        max_output_tokens=16_384 if provider_id == "deepseek" else 4_096,
    )


__all__ = ["INTERNAL_MODEL_ROLES", "get_internal_model_profile"]
