"""Embedding provider registry — pick a provider, pick any model name.

The registry holds *providers* (5-10 stable entries), not (provider × model)
profiles. Adding a new model = NO code change; just point env vars at it.

User config (.env):

    EMBEDDING_PROVIDER=siliconflow      # any key from PROVIDERS below
    EMBEDDING_MODEL=BAAI/bge-m3          # any model that provider hosts
    EMBEDDING_DIM=1024                   # output dim — must match the model

Switching to a different model:
    Same provider:  edit EMBEDDING_MODEL → restart.
    New provider:   edit EMBEDDING_PROVIDER + MODEL + DIM → restart.

Adding a new model variant (e.g. BAAI/bge-large-zh-v1.5 instead of bge-m3):
    Just put the HF id / API model name in EMBEDDING_MODEL. Done.

Adding a new provider:
    One entry in PROVIDERS below. Done.

⚠ Dimension lock-in
-------------------
PostgreSQL generations freeze the complete embedding identity. A model,
revision, dimension, prefix or adapter change requires rebuilding a generation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import settings
from app.core.model_policy import require_local_model

logger = logging.getLogger(__name__)


# ── Provider kinds — drive which client wrapper to instantiate ─────────


ProviderKind = Literal[
    "local_huggingface",  # isolated local broker
    "openai",  # OpenAI's official endpoint shape (uses dimensions= param)
    "openai_compat",  # /v1/embeddings drop-in (SiliconFlow / Jina / DashScope / etc)
]


class EmbeddingValidationError(Exception):
    """Embedding-output / index dimension or count integrity failure (plan §4.5).

    A permanent (non-retryable) ingest error: a returned vector's dim != the
    configured ``EMBEDDING_DIM``, the vector count != the chunk count, or an
    existing index generation's dim differs from ``EMBEDDING_DIM``. The message
    is user-facing — the worker surfaces it like ``EmptyContentError`` — and
    retrying never helps: fix the model/config or rebuild the index.
    """


@dataclass(frozen=True)
class EmbeddingProvider:
    kind: ProviderKind
    api_base: str = ""
    api_key_env: str = ""
    label: str = ""  # human display name for logs / docs
    china_friendly: bool = False


# Small + stable provider catalog. Each new entry needs an API base + the
# env var name that holds the key. Curated suggestions for which models
# work where live in docs/providers.md, NOT in code.
PROVIDERS: dict[str, EmbeddingProvider] = {
    "local": EmbeddingProvider(
        kind="local_huggingface",
        label="本地 HuggingFace",
        china_friendly=True,
    ),
    "openai": EmbeddingProvider(
        kind="openai",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY",
        label="OpenAI",
    ),
    "siliconflow": EmbeddingProvider(
        kind="openai_compat",
        api_base=os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1"),
        api_key_env="SILICONFLOW_API_KEY",
        label="硅基流动",
        china_friendly=True,
    ),
    "jina": EmbeddingProvider(
        kind="openai_compat",
        api_base=os.getenv("JINA_API_BASE", "https://api.jina.ai/v1"),
        api_key_env="JINA_API_KEY",
        label="Jina AI",
    ),
    "dashscope": EmbeddingProvider(
        kind="openai_compat",
        api_base=os.getenv(
            "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        api_key_env="DASHSCOPE_API_KEY",
        label="阿里通义",
        china_friendly=True,
    ),
    "zhipu": EmbeddingProvider(
        kind="openai_compat",
        api_base=os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
        api_key_env="ZHIPU_API_KEY",
        label="智谱 GLM",
        china_friendly=True,
    ),
}


# ── Resolution + factory ───────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedEmbedding:
    """The trio actually fed to the factory: which provider, which model, what dim."""

    provider_id: str
    provider: EmbeddingProvider
    model: str
    dim: int


def resolve_embedding() -> ResolvedEmbedding:
    """Read the three env vars + look the provider up."""
    pid = (settings.EMBEDDING_PROVIDER or "siliconflow").strip().lower()
    if pid not in PROVIDERS:
        raise ValueError(f"Unknown EMBEDDING_PROVIDER: {pid!r}")
    require_local_model(
        "embedding", is_local=PROVIDERS[pid].kind == "local_huggingface"
    )
    model = (settings.EMBEDDING_MODEL or "BAAI/bge-m3").strip()
    dim = int(settings.EMBEDDING_DIM or 1024)
    return ResolvedEmbedding(
        provider_id=pid, provider=PROVIDERS[pid], model=model, dim=dim
    )


def list_providers() -> list[dict[str, Any]]:
    """Catalog dump for docs / Models page."""
    return [
        {
            "id": pid,
            "kind": p.kind,
            "label": p.label,
            "china_friendly": p.china_friendly,
            "api_key_env": p.api_key_env,
            "ready": p.kind == "local_huggingface"
            or (
                settings.AUXILIARY_MODEL_POLICY != "local_only"
                and bool(os.getenv(p.api_key_env, "").strip())
            ),
        }
        for pid, p in PROVIDERS.items()
    ]


def build_embedding() -> Any:
    """Construct the LlamaIndex embedding instance for the current config.

    Imports are local so a lite-mode runtime (provider != local) doesn't pay
    HuggingFace boot cost.
    """
    cfg = resolve_embedding()
    p = cfg.provider

    if p.kind == "local_huggingface":
        from app.local_inference.rag import BrokerEmbedding
        from app.usage.embedding import AccountLocalEmbedding

        # A thin proxy, no weights or CUDA in the web/Celery interpreter.
        return AccountLocalEmbedding(BrokerEmbedding(cfg.model, cfg.dim), cfg.model)

    api_key = os.getenv(p.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(
            f"EMBEDDING_PROVIDER={cfg.provider_id} requires {p.api_key_env} "
            f"to be set in .env"
        )

    if p.kind == "openai":
        from app.usage.embedding import AccountOpenAIEmbedding as OpenAIEmbedding

        logger.info("Embedding: OpenAI model=%s dim=%d", cfg.model, cfg.dim)
        return OpenAIEmbedding(
            model=cfg.model,
            api_key=api_key,
            api_base=p.api_base or None,
            dimensions=cfg.dim,
            max_retries=0,
            embed_batch_size=10,
            usage_provider=cfg.provider_id,
        )

    if p.kind == "openai_compat":
        try:
            from app.usage.embedding import (
                AccountOpenAILikeEmbedding as OpenAILikeEmbedding,
            )
        except ImportError as exc:
            raise RuntimeError(
                "openai_compat embedding requires `llama-index-embeddings-openai-like`. "
                "Run: pip install llama-index-embeddings-openai-like"
            ) from exc
        logger.info(
            "Embedding: %s model=%s dim=%d",
            cfg.provider.label,
            cfg.model,
            cfg.dim,
        )
        return OpenAILikeEmbedding(
            model_name=cfg.model,
            api_key=api_key,
            api_base=p.api_base,
            embed_batch_size=10,
            max_retries=0,
            usage_provider=cfg.provider_id,
        )

    raise RuntimeError(f"Unknown provider kind: {p.kind!r}")


__all__ = [
    "EmbeddingProvider",
    "EmbeddingValidationError",
    "PROVIDERS",
    "ResolvedEmbedding",
    "resolve_embedding",
    "list_providers",
    "build_embedding",
]
