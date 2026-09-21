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

    # Read-only PostgreSQL generation/extension guard. Connectivity is not
    # silently ignored: configured retrieval must really be available.
    from app.rag import hybrid_index

    hybrid_index.validate_index_storage()
