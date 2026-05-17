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
    try:
        cfg = resolve_embedding()
        Settings.embed_model = build_embedding()
        refresh_primary_llm()
        logger.info(
            "RAG embedding ready: provider=%s model=%s dim=%d",
            cfg.provider_id, cfg.model, cfg.dim,
        )
    except Exception as e:
        logger.error(f"Failed to initialize RAG settings: {e}")
        raise
