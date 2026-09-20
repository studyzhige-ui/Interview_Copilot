"""Deterministic identity for a knowledge index generation.

Vector dimensions alone do not define a semantic space.  Every setting that
changes parsing, chunk text, embedding coordinates, or ANN interpretation is
part of the identity.  A different identity receives a different physical
PostgreSQL generation, so same-dimension model changes can never mix silently.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from app.core.config import settings
from app.rag.index.lexical import ANALYZER_VERSION

INDEX_SCHEMA_VERSION = "knowledge-pgvector-v3"
PARSER_CONTRACT_VERSION = "canonical-document-v2"
CLEANING_CONTRACT_VERSION = "canonical-cleaning-v1"
CHUNKER_CONTRACT_VERSION = "structure-aware-v2"
RETRIEVAL_TEXT_VERSION = "structural-prefix-v1"


@dataclass(frozen=True)
class IndexIdentity:
    schema_version: str
    embedding_provider: str
    embedding_model: str
    embedding_revision: str | None
    namespace: str
    embedding_dim: int
    embedding_adapter: str
    similarity_metric: str
    parser_contract: str
    parser_provider: str
    ocr_enabled: bool
    cleaning_contract: str
    chunker_contract: str
    chunk_tokens: int
    chunk_overlap: int
    rerank_input_tokens: int
    query_token_reserve: int
    retrieval_text_contract: str
    analyzer_contract: str
    dense_index_type: str

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=True, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def display_name(self, base_name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]", "_", base_name).strip("_") or "knowledge"
        # Informational label only, never interpolated as a SQL identifier. Actual
        # storage and authorization use the complete 64-character fingerprint.
        return f"{safe[:220]}__{self.fingerprint[:16]}"

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "fingerprint": self.fingerprint}


def _embedding_adapter() -> str:
    if settings.EMBEDDING_PROVIDER != "local":
        return "provider-native-v1"
    from app.local_inference.config import binding_for

    return binding_for(
        "embedding",
        settings.EMBEDDING_MODEL,
        settings.MODEL_REVISIONS_JSON.get(settings.EMBEDDING_MODEL),
        settings.EMBEDDING_DIM,
        settings.LOCAL_EMBED_MAX_TOKENS,
        settings.LOCAL_EMBED_QUERY_PREFIX,
        settings.LOCAL_EMBED_TEXT_PREFIX,
    )


def current_index_identity() -> IndexIdentity:
    return IndexIdentity(
        schema_version=INDEX_SCHEMA_VERSION,
        embedding_provider=(settings.EMBEDDING_PROVIDER or "").strip().lower(),
        embedding_model=(settings.EMBEDDING_MODEL or "").strip(),
        embedding_revision=settings.MODEL_REVISIONS_JSON.get(settings.EMBEDDING_MODEL),
        namespace=settings.RAG_INDEX_NAMESPACE,
        embedding_dim=int(settings.EMBEDDING_DIM),
        embedding_adapter=_embedding_adapter(),
        similarity_metric=(settings.RAG_SIMILARITY_METRIC or "").strip().upper(),
        parser_contract=PARSER_CONTRACT_VERSION,
        parser_provider=(settings.PARSER_PROVIDER or "").strip().lower(),
        ocr_enabled=bool(settings.RAG_OCR_ENABLED),
        cleaning_contract=CLEANING_CONTRACT_VERSION,
        chunker_contract=CHUNKER_CONTRACT_VERSION,
        chunk_tokens=int(settings.RAG_CHUNK_TOKENS),
        chunk_overlap=int(settings.RAG_CHUNK_OVERLAP),
        rerank_input_tokens=int(settings.RAG_RERANK_INPUT_TOKENS),
        query_token_reserve=int(settings.RAG_QUERY_TOKEN_RESERVE),
        retrieval_text_contract=RETRIEVAL_TEXT_VERSION,
        analyzer_contract=ANALYZER_VERSION,
        dense_index_type="EXACT",
    )


def active_index_label() -> str:
    return current_index_identity().display_name(settings.RAG_INDEX_NAMESPACE)


__all__ = [
    "ANALYZER_VERSION",
    "CHUNKER_CONTRACT_VERSION",
    "CLEANING_CONTRACT_VERSION",
    "INDEX_SCHEMA_VERSION",
    "IndexIdentity",
    "PARSER_CONTRACT_VERSION",
    "RETRIEVAL_TEXT_VERSION",
    "active_index_label",
    "current_index_identity",
]
