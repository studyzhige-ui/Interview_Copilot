import logging

from llama_index.core import Settings

from app.core.model_registry import RuntimeLLMProxy, get_llm_for_role, get_profile_for_role
from app.rag.embedding_registry import build_embedding, resolve_embedding

logger = logging.getLogger(__name__)


agent_fast_llm = RuntimeLLMProxy(role="fast")
# Dedicated proxy for mock-interview LLM calls (plan generation, interviewer
# responses, batch evaluation). Separate from `agent_fast_llm` so the user can
# pick a different model for mock from the Models page.
mock_interview_llm = RuntimeLLMProxy(role="mock_interview")


def refresh_primary_llm() -> None:
    profile = get_profile_for_role("primary")
    Settings.llm = get_llm_for_role("primary")
    logger.info(
        "Primary LLM ready: provider=%s model=%s",
        profile.provider,
        profile.model,
    )


def init_rag_settings():
    """Initialize global LlamaIndex Settings: embedding + primary LLM.

    Embedding provider is selected via ``EMBEDDING_PROVIDER`` + ``EMBEDDING_MODEL``
    + ``EMBEDDING_DIM`` env vars. Default ``local`` preserves the original
    full-mode behaviour (downloads from HuggingFace, runs on local GPU/CPU);
    set ``EMBEDDING_PROVIDER`` to ``siliconflow`` / ``openai`` / etc for lite
    mode where no local model download / GPU is required.
    """
    # Embedding is REQUIRED for RAG (query + document vectors); a failure here
    # is fatal — surface it rather than silently degrading retrieval.
    try:
        cfg = resolve_embedding()
        Settings.embed_model = build_embedding()
        logger.info(
            "RAG embedding ready: provider=%s model=%s dim=%d",
            cfg.provider_id, cfg.model, cfg.dim,
        )
    except Exception as e:
        logger.error("Failed to initialize embedding (fatal): %s", e)
        raise

    # Primary LLM: resolve eagerly (warm + validated) when the model catalog is
    # populated. When the catalog is COLD — a fresh environment before
    # ``scripts/refresh_models.py`` / the daily Celery beat has seeded it — do
    # NOT crash startup: degrade to a lazy ``RuntimeLLMProxy`` that resolves on
    # first use (by which point the catalog is seeded; if it still isn't, a
    # single LLM call fails gracefully instead of the whole app refusing to
    # boot). The fast / mock_interview roles are already lazy proxies for this
    # same reason.
    try:
        refresh_primary_llm()
    except Exception as e:  # noqa: BLE001 — catalog cold / vendor /v1/models hiccup
        logger.warning(
            "Primary LLM not resolvable at startup (%s); using a lazy proxy "
            "until the model catalog is populated "
            "(scripts/refresh_models.py or the daily Celery beat).", e,
        )
        Settings.llm = RuntimeLLMProxy(role="primary")
