"""Unified Milvus 2.6 native dense + server-side BM25 hybrid for ALL retrieval
collections (knowledge, resume, memory-ability).

ONE config-driven implementation (raw pymilvus, MilvusClient). Each collection
declares only its name + its extra scalar fields; everything else is shared:

  * ``id``      VARCHAR primary key — the domain row id.
  * ``user_id`` INT64 — the stable users.id tenant scope key (EVERY collection).
  * <scalars>   domain VARCHAR fields (e.g. source_kind, section_type, topic).
  * ``text``    VARCHAR (chinese analyzer) — the indexed text (a Postgres copy).
  * ``dense``   FLOAT_VECTOR — the embedding (IP metric, HNSW).
  * ``sparse``  SPARSE_FLOAT_VECTOR — server-side BM25 over ``text`` via a Milvus
    ``Function`` (Milvus owns the corpus stats; NO client sparse model, NO fit).

Retrieval is a single ``hybrid_search`` (dense ANN + BM25, fused by RRF) scoped
to the caller's ``user_id`` pk. Postgres stays the fact source; Milvus is an
index-only copy. This module owns the collection schemas directly, so no
retrieval collection flows through LlamaIndex's vector-store abstraction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_DENSE_FIELD = "dense"
_SPARSE_FIELD = "sparse"
_TEXT_FIELD = "text"
_TEXT_MAX = 65535
_ID_MAX = 128
_SCALAR_MAX = 512
# jieba-based CJK tokenizer (corpus is Chinese-heavy; still splits embedded
# English on whitespace). Built into Milvus 2.6's analyzer set.
_ANALYZER_PARAMS = {"type": "chinese"}


@dataclass(frozen=True)
class _Scalar:
    name: str
    nullable: bool = False
    max_length: int = _SCALAR_MAX


@dataclass(frozen=True)
class HybridCollection:
    """A retrieval collection's identity + its domain scalar fields. The common
    ``id`` / ``user_id`` / ``text`` / ``dense`` / ``sparse`` fields (+ the BM25
    function) are added automatically by ``ensure_collection``."""

    name: str
    scalars: tuple[_Scalar, ...] = ()

    @property
    def output_fields(self) -> list[str]:
        """Scalar fields returned by hybrid_search (``id`` comes back implicitly)."""
        return [_TEXT_FIELD, "user_id", *[s.name for s in self.scalars]]


# ── The three retrieval collections — identical tenant model (user_id INT64) ──
KNOWLEDGE = HybridCollection(
    name=settings.MILVUS_COLLECTION,
    scalars=(_Scalar("source_kind"), _Scalar("document_id", nullable=True)),
)
RESUME = HybridCollection(
    name=settings.RESUME_MILVUS_COLLECTION,
    scalars=(
        _Scalar("resume_id"),
        _Scalar("section_type"),
        _Scalar("title", max_length=_TEXT_MAX),
    ),
)
ABILITY = HybridCollection(
    name=settings.MEMORY_ABILITY_MILVUS_COLLECTION,
    scalars=(
        _Scalar("topic", max_length=_TEXT_MAX),
        _Scalar("skill_type"),
        _Scalar("mastery_level"),
        _Scalar("summary", nullable=True, max_length=_TEXT_MAX),
    ),
)

_client: Any = None
_client_lock = Lock()
_ensured: set[str] = set()
_ensure_lock = Lock()


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            from pymilvus import MilvusClient

            _client = MilvusClient(uri=settings.MILVUS_URI)
        return _client


def _eq(field_name: str, value: Any) -> str:
    """A safe ``field == value`` clause. Ints are cast; strings are rejected if
    they contain quote/backslash chars so no caller can inject filter syntax
    (scope keys are int pks; the rest are fixed enum values or generated ids)."""
    if isinstance(value, int):
        return f"{field_name} == {value}"
    sval = str(value)
    if '"' in sval or "\\" in sval:
        raise ValueError(f"unsafe Milvus filter value for {field_name!r}: {sval!r}")
    return f'{field_name} == "{sval}"'


def _scope_expr(user_pk: int, filters: Optional[dict[str, Any]] = None) -> str:
    """The tenant-scoped Milvus filter expr: ``user_id == <pk>`` plus any extra
    equality filters (every value safety-checked via ``_eq``)."""
    expr = _eq("user_id", int(user_pk))
    for fname, fval in (filters or {}).items():
        if fval is not None:
            expr += " && " + _eq(fname, fval)
    return expr


def ensure_collection(coll: HybridCollection) -> None:
    """Create the collection (common fields + domain scalars + BM25 function +
    dense/sparse indexes) once. Idempotent."""
    from pymilvus import DataType, Function, FunctionType

    client = _get_client()
    if coll.name in _ensured and client.has_collection(coll.name):
        return
    with _ensure_lock:
        if client.has_collection(coll.name):
            _ensured.add(coll.name)
            return
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=_ID_MAX)
        schema.add_field("user_id", DataType.INT64)
        for s in coll.scalars:
            schema.add_field(
                s.name, DataType.VARCHAR, max_length=s.max_length, nullable=s.nullable,
            )
        schema.add_field(
            _TEXT_FIELD, DataType.VARCHAR, max_length=_TEXT_MAX,
            enable_analyzer=True, analyzer_params=_ANALYZER_PARAMS,
        )
        schema.add_field(_DENSE_FIELD, DataType.FLOAT_VECTOR, dim=settings.EMBEDDING_DIM)
        schema.add_field(_SPARSE_FIELD, DataType.SPARSE_FLOAT_VECTOR)
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
        client.create_collection(coll.name, schema=schema, index_params=index_params)
        client.load_collection(coll.name)
        _ensured.add(coll.name)
        logger.info(
            "Created Milvus hybrid collection %s (dense dim=%s + server-side BM25 sparse)",
            coll.name, settings.EMBEDDING_DIM,
        )


def insert(coll: HybridCollection, rows: list[dict[str, Any]]) -> None:
    """Insert rows: ``{id, user_id(int pk), <scalars>, text, dense}``. The
    ``sparse`` field is produced server-side by the BM25 function — never supply
    it. ``text`` is truncated to the VARCHAR limit."""
    if not rows:
        return
    ensure_collection(coll)
    for r in rows:
        t = r.get(_TEXT_FIELD)
        if t and len(t) > _TEXT_MAX:
            r[_TEXT_FIELD] = t[:_TEXT_MAX]
    _get_client().insert(coll.name, data=rows)


def delete(coll: HybridCollection, expr: str) -> None:
    client = _get_client()
    if client.has_collection(coll.name):
        client.delete(coll.name, filter=expr)


def delete_by_field(coll: HybridCollection, field_name: str, value: Any) -> None:
    """Delete every row matching ``field == value`` (e.g. document_id / upload_id
    / a user pk). No-op for an empty value."""
    if value is None or value == "":
        return
    delete(coll, _eq(field_name, value))


def delete_by_user(coll: HybridCollection, user_pk: int) -> None:
    delete(coll, _eq("user_id", int(user_pk)))


def hybrid_search(
    coll: HybridCollection,
    *,
    query_text: str,
    query_dense: list[float],
    user_pk: int,
    top_k: int,
    filters: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Dense ANN + server-side BM25, fused by RRF, scoped to ``user_pk`` (+ any
    extra equality ``filters``). Returns ``[{id, text, score, <scalars>}]`` in
    RRF order. Empty list if the collection doesn't exist yet."""
    from pymilvus import AnnSearchRequest, RRFRanker

    client = _get_client()
    if not client.has_collection(coll.name):
        return []
    expr = _scope_expr(user_pk, filters)
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
        coll.name, [dense_req, sparse_req], ranker=RRFRanker(),
        limit=top_k, output_fields=coll.output_fields,
    )
    hits = results[0] if results else []
    out: list[dict[str, Any]] = []
    for h in hits:
        ent = h.get("entity", {}) or {}
        row: dict[str, Any] = {
            "id": h.get("id"),
            "text": ent.get(_TEXT_FIELD, ""),
            "score": float(h.get("distance", 0.0) or 0.0),
            "user_id": ent.get("user_id"),
        }
        for s in coll.scalars:
            row[s.name] = ent.get(s.name)
        out.append(row)
    return out


__all__ = [
    "HybridCollection",
    "KNOWLEDGE",
    "RESUME",
    "ABILITY",
    "ensure_collection",
    "insert",
    "delete",
    "delete_by_field",
    "delete_by_user",
    "hybrid_search",
]
