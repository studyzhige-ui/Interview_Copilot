"""Reranker provider registry — pick a provider, pick any model name.

Same shape as embedding_registry: small PROVIDERS dict + free-form
``RERANKER_MODEL`` env. Adding new model variants (bge-reranker-large vs
v2-m3 vs v2-gemma) needs zero code change.

User config (.env):

    RERANKER_PROVIDER=siliconflow                    # any key from PROVIDERS
    RERANKER_MODEL=BAAI/bge-reranker-v2-m3           # any model that provider supports
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

import httpx
from llama_index.core.bridge.pydantic import Field
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle

from app.core.config import settings

logger = logging.getLogger(__name__)


ProviderKind = Literal["local_hf_crossencoder", "remote_openai_style"]


@dataclass(frozen=True)
class RerankerProvider:
    kind: ProviderKind
    api_base: str = ""
    api_key_env: str = ""
    label: str = ""
    china_friendly: bool = False


# Catalog of providers — every entry that can talk reranker. The actual
# model name is supplied by the user via RERANKER_MODEL.
PROVIDERS: dict[str, RerankerProvider] = {
    "local": RerankerProvider(
        kind="local_hf_crossencoder",
        label="本地 HuggingFace SBERT",
        china_friendly=True,
    ),
    "siliconflow": RerankerProvider(
        kind="remote_openai_style",
        api_base=os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1"),
        api_key_env="SILICONFLOW_API_KEY",
        label="硅基流动",
        china_friendly=True,
    ),
    "dashscope": RerankerProvider(
        kind="remote_openai_style",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY",
        label="阿里通义",
        china_friendly=True,
    ),
    "jina": RerankerProvider(
        kind="remote_openai_style",
        api_base=os.getenv("JINA_API_BASE", "https://api.jina.ai/v1"),
        api_key_env="JINA_API_KEY",
        label="Jina AI",
    ),
    "cohere": RerankerProvider(
        kind="remote_openai_style",
        api_base=os.getenv("COHERE_API_BASE", "https://api.cohere.com/v2"),
        api_key_env="COHERE_API_KEY",
        label="Cohere",
    ),
}


@dataclass(frozen=True)
class ResolvedReranker:
    provider_id: str
    provider: RerankerProvider
    model: str


def resolve_reranker() -> ResolvedReranker:
    pid = (settings.RERANKER_PROVIDER or "local").strip().lower()
    if pid not in PROVIDERS:
        logger.warning(
            "Unknown RERANKER_PROVIDER=%r, falling back to 'local'", pid,
        )
        pid = "local"
    model = (settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3").strip()
    return ResolvedReranker(provider_id=pid, provider=PROVIDERS[pid], model=model)


def list_providers() -> list[dict[str, Any]]:
    return [
        {
            "id": pid,
            "kind": p.kind,
            "label": p.label,
            "china_friendly": p.china_friendly,
            "api_key_env": p.api_key_env,
            "ready": p.kind == "local_hf_crossencoder" or bool(os.getenv(p.api_key_env, "").strip()),
        }
        for pid, p in PROVIDERS.items()
    ]


# ── Remote rerank postprocessor (unchanged) ────────────────────────────


class RemoteAPIRerank(BaseNodePostprocessor):
    """Generic OpenAI-style ``/rerank`` postprocessor.

    Posts the candidate node texts to the provider, takes back the sorted
    indices + scores, and returns the top-N as ``NodeWithScore``. Falls
    back to passing the input through (no re-ranking) on transport error
    so a flaky upstream doesn't kill the whole RAG turn.
    """

    api_base: str = Field()
    api_key: str = Field()
    model: str = Field()
    top_n: int = Field(default=5)
    timeout: float = Field(default=15.0)

    @classmethod
    def class_name(cls) -> str:
        return "RemoteAPIRerank"

    def _postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        if not nodes or query_bundle is None:
            return nodes[: self.top_n]

        documents = [n.node.get_content() for n in nodes]
        payload = {
            "model": self.model,
            "query": query_bundle.query_str,
            "documents": documents,
            "top_n": min(self.top_n, len(documents)),
        }
        url = f"{self.api_base.rstrip('/')}/rerank"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Remote rerank failed (%s); returning unranked top-N: %s",
                self.model, exc,
            )
            return nodes[: self.top_n]

        # Cohere v2 / SiliconFlow / Jina shape: {"results": [{"index": i,
        # "relevance_score": s, ...}, ...]} sorted desc. DashScope wraps
        # in {"output": {"results": [...]}}.
        results = body.get("results") or body.get("output", {}).get("results") or []
        if not results:
            logger.warning("Remote rerank returned no results; passing through")
            return nodes[: self.top_n]

        out: list[NodeWithScore] = []
        for r in results[: self.top_n]:
            idx = r.get("index")
            score = r.get("relevance_score") or r.get("score")
            if idx is None or idx >= len(nodes):
                continue
            n = nodes[idx]
            out.append(NodeWithScore(node=n.node, score=float(score) if score is not None else n.score))
        return out


def build_reranker(top_n: int) -> Any:
    """Construct the LlamaIndex postprocessor for the active reranker config."""
    cfg = resolve_reranker()
    p = cfg.provider

    if p.kind == "local_hf_crossencoder":
        from app.core.hf_runtime import (
            prepare_hf_runtime,
            resolve_local_snapshot,
            format_missing_model_error,
        )
        from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank

        prepare_hf_runtime()
        local_path = resolve_local_snapshot(cfg.model)
        if local_path is None:
            raise RuntimeError(
                format_missing_model_error(
                    model_id=cfg.model,
                    role="Reranker",
                    filter_substring="rerank",
                    fix_hint="python scripts/init_models.py --only reranker",
                )
            )
        logger.info("Reranker: local model=%s top_n=%d", cfg.model, top_n)
        return SentenceTransformerRerank(model=local_path, top_n=top_n)

    if p.kind == "remote_openai_style":
        api_key = os.getenv(p.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(
                f"RERANKER_PROVIDER={cfg.provider_id} requires {p.api_key_env}"
                " to be set in .env"
            )
        logger.info(
            "Reranker: %s model=%s top_n=%d", p.label, cfg.model, top_n,
        )
        return RemoteAPIRerank(
            api_base=p.api_base,
            api_key=api_key,
            model=cfg.model,
            top_n=top_n,
        )

    raise RuntimeError(f"Unknown provider kind: {p.kind!r}")


__all__ = [
    "RerankerProvider",
    "PROVIDERS",
    "ResolvedReranker",
    "resolve_reranker",
    "list_providers",
    "build_reranker",
]
