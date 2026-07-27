import logging

from llama_index.core import Settings

from app.core.llm_client_factory import RuntimeLLMProxy, get_llm_for_role
from app.core.user_model_selection import get_profile_for_role
from app.rag.embedding_registry import build_embedding, resolve_embedding

logger = logging.getLogger(__name__)


def refresh_primary_llm() -> None:
    """(Re)bind the SYSTEM-view primary LLM into LlamaIndex ``Settings.llm``.

    Settings.llm is the system path only (MDL-1): LlamaIndex components with
    no request context (RAG synthesizers etc). Every user-facing pipeline —
    L1 chat, planner, mock, memory, resume, analysis — resolves its own LLM
    explicitly via ``get_llm_for_role(role, user_id=owner)``.
    """
    profile = get_profile_for_role("primary")
    Settings.llm = get_llm_for_role("primary")
    logger.info(
        "Primary LLM ready: provider=%s model=%s",
        profile.provider,
        profile.model,
    )


def init_rag_settings(*, include_primary_llm: bool = True):
    """Initialize global embedding settings and, for API processes, the LLM.

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
            cfg.provider_id,
            cfg.model,
            cfg.dim,
        )
    except Exception as e:
        logger.error("Failed to initialize embedding (fatal): %s", e)
        raise

    # Startup dim guard (plan §4.5.1): fail loud at boot if an existing Milvus
    # collection's dense dim no longer matches EMBEDDING_DIM (model/dim changed
    # without a rebuild). Best-effort on connectivity; raises on a real mismatch.
    from app.rag import milvus_hybrid

    milvus_hybrid.validate_existing_dims(
        milvus_hybrid.KNOWLEDGE,
        milvus_hybrid.RESUME,
        milvus_hybrid.ABILITY,
    )

    if not include_primary_llm:
        return

    # Primary LLM: resolve eagerly (warm + validated) when the model catalog is
    # populated. When the catalog is COLD — a fresh environment before
    # ``scripts/refresh_models.py`` / the daily Celery beat has seeded it — do
    # NOT crash startup: degrade to a lazy ``RuntimeLLMProxy`` that resolves on
    # first use (by which point the catalog is seeded; if it still isn't, a
    # single LLM call fails gracefully instead of the whole app refusing to
    # boot).
    try:
        refresh_primary_llm()
    except Exception as e:  # noqa: BLE001 — catalog cold / vendor /v1/models hiccup
        logger.warning(
            "Primary LLM not resolvable at startup (%s); using a lazy proxy "
            "until the model catalog is populated "
            "(scripts/refresh_models.py or the daily Celery beat).",
            e,
        )
        Settings.llm = RuntimeLLMProxy(role="primary")
