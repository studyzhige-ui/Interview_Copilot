"""Milvus 2.6 native dense + BM25 hybrid for the knowledge RAG collection.

Replaces the old LlamaIndex ``MilvusVectorStore`` (dense-only) + the separate
Postgres-sourced BM25 fusion. ONE Milvus collection now carries everything:

  * ``dense``  FLOAT_VECTOR      — the embedding (IP metric, HNSW).
  * ``text``   VARCHAR (analyzer) — the chunk text.
  * ``sparse`` SPARSE_FLOAT_VECTOR — server-side BM25 over ``text`` via a Milvus
    ``Function`` (Milvus computes + maintains the corpus BM25 stats; there is NO
    client-side sparse model and NO fitting step).
  * scope scalars: ``user_id`` (INT64 = the stable users.id), ``source_kind``,
    ``document_id``.

Retrieval is a single ``hybrid_search`` — dense ANN + BM25, fused by RRF — scoped
to the caller's ``user_id`` pk (multi-tenant isolation). The dense vector is
produced by the configured embedding model (LlamaIndex ``Settings.embed_model``);
the sparse/BM25 vector is produced entirely server-side from ``text``.

This module owns the collection schema directly (raw pymilvus), so the knowledge
collection no longer flows through LlamaIndex's vector-store abstraction.
"""
from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

COLLECTION = settings.MILVUS_COLLECTION
_DENSE_FIELD = "dense"
_SPARSE_FIELD = "sparse"
_TEXT_FIELD = "text"
_TEXT_MAX = 65535
# jieba-based CJK tokenizer — the corpus is Chinese-heavy (it still splits
# embedded English on whitespace). Built into Milvus 2.6's analyzer set.
_ANALYZER_PARAMS = {"type": "chinese"}

_client: Any = None
_lock = Lock()


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            from pymilvus import MilvusClient

            _client = MilvusClient(uri=settings.MILVUS_URI)
        return _client


def ensure_collection() -> None:
    """Create the hybrid collection (dense + BM25 sparse + scope scalars) once.

    Idempotent — a no-op if the collection already exists. The BM25 ``Function``
    wires ``text`` -> ``sparse`` so inserts only supply ``text``; Milvus fills the
    sparse vector server-side.
    """
    from pymilvus import DataType, Function, FunctionType

    client = _get_client()
    if client.has_collection(COLLECTION):
        return
    with _lock:
        if client.has_collection(COLLECTION):
            return
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("user_id", DataType.INT64)
        schema.add_field("source_kind", DataType.VARCHAR, max_length=64)
        schema.add_field("document_id", DataType.VARCHAR, max_length=128, nullable=True)
        schema.add_field(
            _TEXT_FIELD, DataType.VARCHAR, max_length=_TEXT_MAX,
            enable_analyzer=True, analyzer_params=_ANALYZER_PARAMS,
        )
        schema.add_field(_DENSE_FIELD, DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM)
        schema.add_field(_SPARSE_FIELD, DataType.SPARSE_FLOAT_VECTOR)
        # Server-side BM25: text -> sparse. Milvus owns the corpus stats.
        schema.add_function(Function(
            name="bm25_text_to_sparse",
            function_type=FunctionType.BM25,
            input_field_names=[_TEXT_FIELD],
            output_field_names=[_SPARSE_FIELD],
        ))
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name=_DENSE_FIELD,
            index_type=settings.MILVUS_DENSE_INDEX_TYPE,
            metric_type=settings.MILVUS_SIMILARITY_METRIC,
            params={
                "M": settings.MILVUS_HNSW_M,
                "efConstruction": settings.MILVUS_HNSW_EF_CONSTRUCTION,
            },
        )
        index_params.add_index(
            field_name=_SPARSE_FIELD,
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        client.create_collection(COLLECTION, schema=schema, index_params=index_params)
        client.load_collection(COLLECTION)
        logger.info(
            "Created Milvus hybrid collection %s (dense dim=%s + server-side BM25 sparse)",
            COLLECTION, settings.EMBEDDING_DIM,
        )


def insert(rows: list[dict[str, Any]]) -> None:
    """Insert chunk rows. Each row:
    ``{id, user_id(int pk), source_kind, document_id|None, text, dense:list[float]}``.
    The ``sparse`` field is produced server-side by the BM25 function — do NOT
    supply it. ``text`` is truncated to the VARCHAR limit.
    """
    if not rows:
        return
    ensure_collection()
    for r in rows:
        if r.get("text") and len(r["text"]) > _TEXT_MAX:
            r["text"] = r["text"][:_TEXT_MAX]
    _get_client().insert(COLLECTION, data=rows)


def delete_by_document(document_id: str) -> None:
    """Drop all chunks of one knowledge document (re-ingest / hard delete)."""
    if not document_id:
        return
    client = _get_client()
    if client.has_collection(COLLECTION):
        client.delete(COLLECTION, filter=f'document_id == "{document_id}"')


def delete_by_user(user_pk: int) -> None:
    """Drop every chunk owned by a user (account wipe)."""
    client = _get_client()
    if client.has_collection(COLLECTION):
        client.delete(COLLECTION, filter=f"user_id == {int(user_pk)}")


def _scope_expr(user_pk: int, source_kind: Optional[str]) -> str:
    expr = f"user_id == {int(user_pk)}"
    # source_kind is a fixed enum value (official_docs / interview_qa / ...);
    # validate the charset before interpolating so no caller can inject filter
    # syntax into the boolean expression.
    if source_kind and re.fullmatch(r"[a-z0-9_]+", source_kind):
        expr += f' && source_kind == "{source_kind}"'
    return expr


def hybrid_search(
    *,
    query_text: str,
    query_dense: list[float],
    user_pk: int,
    source_kind: Optional[str],
    top_k: int,
) -> list[dict[str, Any]]:
    """Dense ANN + server-side BM25, fused by RRF, scoped to ``user_pk``.

    Returns ``[{id, text, score, source_kind, document_id, user_id}]`` (RRF order).
    Empty list if the collection doesn't exist yet (nothing ingested).
    """
    from pymilvus import AnnSearchRequest, RRFRanker

    client = _get_client()
    if not client.has_collection(COLLECTION):
        return []
    expr = _scope_expr(user_pk, source_kind)
    dense_req = AnnSearchRequest(
        data=[query_dense], anns_field=_DENSE_FIELD,
        param={"metric_type": settings.MILVUS_SIMILARITY_METRIC,
               "params": {"ef": settings.MILVUS_HNSW_EF_SEARCH}},
        limit=top_k, expr=expr,
    )
    sparse_req = AnnSearchRequest(
        data=[query_text], anns_field=_SPARSE_FIELD,
        param={"metric_type": "BM25"},
        limit=top_k, expr=expr,
    )
    results = client.hybrid_search(
        COLLECTION, [dense_req, sparse_req], ranker=RRFRanker(),
        limit=top_k,
        output_fields=[_TEXT_FIELD, "user_id", "source_kind", "document_id"],
    )
    hits = results[0] if results else []
    out: list[dict[str, Any]] = []
    for h in hits:
        ent = h.get("entity", {}) or {}
        out.append({
            "id": h.get("id"),
            "text": ent.get(_TEXT_FIELD, ""),
            "score": float(h.get("distance", 0.0) or 0.0),
            "source_kind": ent.get("source_kind"),
            "document_id": ent.get("document_id"),
            "user_id": ent.get("user_id"),
        })
    return out


__all__ = [
    "COLLECTION",
    "ensure_collection",
    "insert",
    "delete_by_document",
    "delete_by_user",
    "hybrid_search",
]
