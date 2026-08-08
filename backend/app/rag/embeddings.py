import logging

from llama_index.core import Settings

from app.rag.embedding_registry import build_embedding, resolve_embedding

logger = logging.getLogger(__name__)


def init_rag_settings() -> None:
    """Initialize the process-local embedding model and validate index dimensions.

    Embedding provider is selected via ``EMBEDDING_PROVIDER`` + ``EMBEDDING_MODEL``
    + ``EMBEDDING_DIM``. Answer models are deliberately absent from this module:
    every user-facing call resolves the owner's ``primary`` model explicitly,
    while routing and background work use deployment-owned internal roles.
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
