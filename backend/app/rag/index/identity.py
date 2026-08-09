"""Deterministic identity for a knowledge index generation.

Vector dimensions alone do not define a semantic space.  Every setting that
changes parsing, chunk text, embedding coordinates, or ANN interpretation is
part of the identity.  A different identity receives a different physical
Milvus collection, so same-dimension model changes can never mix silently.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from app.core.config import settings

INDEX_SCHEMA_VERSION = "knowledge-rag-v2"
PARSER_CONTRACT_VERSION = "canonical-document-v2"
CLEANING_CONTRACT_VERSION = "canonical-cleaning-v1"
CHUNKER_CONTRACT_VERSION = "structure-aware-v2"
RETRIEVAL_TEXT_VERSION = "structural-prefix-v1"
ANALYZER_VERSION = "milvus-chinese-v1"


@dataclass(frozen=True)
class IndexIdentity:
    schema_version: str
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
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
    hnsw_m: int
    hnsw_ef_construction: int

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=True, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def physical_collection(self, base_name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]", "_", base_name).strip("_") or "knowledge"
        # Milvus collection names are identifiers.  Keep the readable base and
        # append enough digest bits to make accidental collisions negligible.
        return f"{safe[:220]}__{self.fingerprint[:16]}"

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "fingerprint": self.fingerprint}


def current_index_identity() -> IndexIdentity:
    return IndexIdentity(
        schema_version=INDEX_SCHEMA_VERSION,
        embedding_provider=(settings.EMBEDDING_PROVIDER or "").strip().lower(),
        embedding_model=(settings.EMBEDDING_MODEL or "").strip(),
        embedding_dim=int(settings.EMBEDDING_DIM),
        similarity_metric=(settings.MILVUS_SIMILARITY_METRIC or "").strip().upper(),
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
        dense_index_type=(settings.MILVUS_DENSE_INDEX_TYPE or "").strip().upper(),
        hnsw_m=int(settings.MILVUS_HNSW_M),
        hnsw_ef_construction=int(settings.MILVUS_HNSW_EF_CONSTRUCTION),
    )


def active_knowledge_collection_name() -> str:
    return current_index_identity().physical_collection(settings.MILVUS_COLLECTION)


__all__ = [
    "ANALYZER_VERSION",
    "CHUNKER_CONTRACT_VERSION",
    "CLEANING_CONTRACT_VERSION",
    "INDEX_SCHEMA_VERSION",
    "IndexIdentity",
    "PARSER_CONTRACT_VERSION",
    "RETRIEVAL_TEXT_VERSION",
    "active_knowledge_collection_name",
    "current_index_identity",
]
