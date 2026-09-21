"""Deployment policy for non-LLM models, separate from provider credentials."""

from app.core.config import settings


class LocalModelPolicyError(RuntimeError):
    """Do not replace unavailable local inference with an online provider."""


def require_local_model(role: str, *, is_local: bool) -> None:
    if settings.AUXILIARY_MODEL_POLICY == "local_only" and not is_local:
        raise LocalModelPolicyError(
            f"local_model_required:{role}: configure a local adapter; "
            "no model request was sent"
        )
