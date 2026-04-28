import logging

from app.core.hf_runtime import prepare_hf_runtime, resolve_local_snapshot

HF_CACHE_DIR = prepare_hf_runtime()

import torch
from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from app.core.config import settings
from app.core.model_registry import RuntimeLLMProxy, get_llm_for_role, get_profile_for_role

logger = logging.getLogger(__name__)


def _prepare_hf_runtime() -> None:
    prepare_hf_runtime()


agent_fast_llm = RuntimeLLMProxy(role="fast")


def refresh_primary_llm() -> None:
    profile = get_profile_for_role("primary")
    Settings.llm = get_llm_for_role("primary")
    logger.info(
        "Primary LLM ready: provider=%s model=%s",
        profile.provider,
        profile.model,
    )


def init_rag_settings():
    """
    Initialize global LlamaIndex Settings.
    """
    try:
        hf_cache_dir = prepare_hf_runtime()
        if settings.EMBEDDING_DEVICE != "auto":
            device = settings.EMBEDDING_DEVICE
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Detecting hardware: Using %s for embeddings.", device.upper())

        embedding_model_name = (
            resolve_local_snapshot(settings.EMBEDDING_MODEL_ID) or settings.EMBEDDING_MODEL_ID
        )
        embed_model = HuggingFaceEmbedding(
            model_name=embedding_model_name,
            device=device,
            cache_folder=str(hf_cache_dir),
        )

        Settings.embed_model = embed_model
        refresh_primary_llm()

        logger.info(
            "RAG settings initialized with embedding model '%s'.",
            settings.EMBEDDING_MODEL_ID,
        )
    except Exception as e:
        logger.error(f"Failed to initialize RAG settings: {e}")
        raise
