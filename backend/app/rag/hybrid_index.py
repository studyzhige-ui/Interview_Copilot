"""One PostgreSQL retrieval repository: exact pgvector + tenant-scoped BM25.

The canonical document/chunk/file joins are applied BEFORE ranking and corpus
statistics, not merely as a final user-interface filter. Replacement and the
published generation share one transaction. No DDL, model download or external
service fallback occurs in a request.

Official operator semantics: github.com/pgvector/pgvector, pgvector-python.
Exact search is the explicit local baseline; it avoids cross-tenant ANN recall
interference. Resource limits return unavailable, never silently fewer facts.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select, delete, text, or_, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import database
from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.retrieval_index import RetrievalEntry, RetrievalGeneration
from app.rag.index.identity import current_index_identity
from app.rag.index.lexical import term_counts, BM25_K1, BM25_B
from app.rag.index.vector_validation import validate_vector


from app.rag.index.source import IndexSourceChanged, SourceSnapshot, source_snapshot


class RetrievalIndexUnavailable(RuntimeError):
    """Configured local retrieval storage cannot honor the request."""


def _limits(db: Session) -> None:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        raise RetrievalIndexUnavailable(
            "pgvector requires PostgreSQL; no silent SQLite vector fallback"
        )
    # set_config(..., true) is transaction-local and safely parameterized.
    db.execute(
        text("SELECT set_config('statement_timeout', :v, true)"),
        {"v": str(settings.RAG_INDEX_STATEMENT_TIMEOUT_MS)},
    )
    db.execute(
        text("SELECT set_config('lock_timeout', :v, true)"),
        {"v": str(settings.RAG_INDEX_LOCK_TIMEOUT_MS)},
    )


def validate_index_storage() -> None:
    """Read-only health/schema guard. Missing extension is a deployment error."""
    identity = current_index_identity()
    with database.SessionLocal() as db:
        _limits(db)
        if (
            db.execute(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            ).scalar()
            is None
        ):
            raise RetrievalIndexUnavailable(
                "pgvector extension is missing; apply the database migrations"
            )
        generation = db.get(RetrievalGeneration, identity.fingerprint)
        if generation is not None and (
            generation.embedding_dim != identity.embedding_dim
            or generation.identity_json != identity.to_dict()
        ):
            raise RetrievalIndexUnavailable(
                "stored generation identity does not match its fingerprint"
            )


def _register_generation(db: Session) -> str:
    identity = current_index_identity()
    values = dict(
        fingerprint=identity.fingerprint,
        embedding_dim=identity.embedding_dim,
        identity_json=identity.to_dict(),
    )
    db.execute(
        pg_insert(RetrievalGeneration)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["fingerprint"])
    )
    row = db.get(RetrievalGeneration, identity.fingerprint, populate_existing=True)
    if (
        row is None
        or row.embedding_dim != identity.embedding_dim
        or row.identity_json != identity.to_dict()
    ):
        raise RetrievalIndexUnavailable("immutable retrieval generation mismatch")
    return identity.fingerprint


def replace_document(
    *,
    user_pk: int,
    document_id: str,
    source_kind: str,
    rows: list[dict[str, Any]],
    expected_source: SourceSnapshot | None = None,
    embedding_profile: dict[str, Any] | None = None,
) -> None:
    """Validate a prepared chunk snapshot, replace its projection, publish once.

    Each row has id, source_text and prefix-bearing text, plus its dense vector.
    The source snapshot is compared under the document lock. A competing delete,
    reparse or correction cannot make a late successful embedding authoritative.
    """
    _validate_owner(user_pk)
    if len(rows) > settings.RAG_INDEX_MAX_DOCUMENT_CHUNKS:
        raise ValueError("document exceeds index chunk capacity")
    identity = current_index_identity()
    prepared = []
    ids: set[str] = set()
    for row in rows:
        key = row.get("id")
        source = row.get("source_text")
        passage = row.get("text")
        if (
            not isinstance(key, str)
            or not key
            or key in ids
            or not isinstance(source, str)
            or not source.strip()
            or not isinstance(passage, str)
            or not passage.strip()
        ):
            raise ValueError(
                "index rows require unique identities and nonempty exact texts"
            )
        ids.add(key)
        counts = term_counts(passage)
        prepared.append(
            {
                "node_id": key,
                "source_hash": hashlib.sha256(source.encode()).hexdigest(),
                "passage": passage,
                "embedding": validate_vector(
                    row["dense"], expected_dim=identity.embedding_dim, label="索引"
                ),
                "term_counts": counts,
                "lexical_terms": sorted(counts),
                "token_count": sum(counts.values()),
            }
        )
    with database.SessionLocal() as db:
        _limits(db)
        doc = db.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
        )
        if (
            doc is None
            or doc.deleted_at is not None
            or doc.status in {"deleting", "deleted", "stale"}
        ):
            raise IndexSourceChanged("document is no longer indexable")
        if doc.user_id != user_pk or doc.source_kind != source_kind:
            raise PermissionError("canonical document ownership/source mismatch")
        if doc.source_kind == "chat_attachment":
            raise PermissionError(
                "private attachments use exact authorized reads, not the shared retrieval corpus"
            )
        if doc.file_asset_id:
            asset = db.get(FileAsset, doc.file_asset_id)
            if (
                asset is None
                or asset.user_id != user_pk
                or asset.deleted_at is not None
                or asset.upload_status not in {"uploaded", "consumed"}
            ):
                raise PermissionError("canonical source file owner mismatch")
        if expected_source is not None and source_snapshot(db, doc) != expected_source:
            raise IndexSourceChanged("document version changed while embedding")
        chunks = list(
            db.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.index_status != "deleted",
                )
                .with_for_update()
            )
        )
        by_node = {chunk.node_id: chunk for chunk in chunks}
        if set(by_node) != ids or len(chunks) != len(ids):
            raise IndexSourceChanged("the complete canonical chunk set changed")
        for row in prepared:
            chunk = by_node[row["node_id"]]
            if chunk.user_id != user_pk or chunk.source_kind != source_kind:
                raise PermissionError("canonical chunk owner/source mismatch")
            actual_hash = hashlib.sha256(chunk.text.encode()).hexdigest()
            if actual_hash != row["source_hash"]:
                raise IndexSourceChanged("canonical chunk text changed while embedding")
            row["chunk_id"] = chunk.id
        # Register only after source authorization; no user content belongs in
        # this identity. Concurrent registrations are conflict-safe.
        generation = _register_generation(db)
        db.execute(
            delete(RetrievalEntry).where(
                RetrievalEntry.generation == generation,
                RetrievalEntry.document_id == document_id,
            )
        )
        if prepared:
            db.execute(
                pg_insert(RetrievalEntry),
                [
                    dict(
                        row,
                        generation=generation,
                        document_id=document_id,
                        user_id=user_pk,
                        source_kind=source_kind,
                    )
                    for row in prepared
                ],
            )
        for chunk in chunks:
            if embedding_profile is not None:
                import json

                try:
                    metadata = json.loads(chunk.metadata_json or "{}")
                except (TypeError, ValueError):
                    metadata = {}
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["embedding_profile"] = embedding_profile
                chunk.metadata_json = json.dumps(metadata, ensure_ascii=False)
            chunk.index_status = "indexed"
            chunk.text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()
        doc.index_fingerprint = generation
        db.commit()


def delete_by_field(field_name: str, value: Any, *, user_pk: int | None = None) -> None:
    """Administrative projection cleanup; user-facing callers always pass owner.

    Only exact stable document/node/user keys are accepted. This cannot delete
    source documents, raw audio, or any canonical facts.
    """
    columns = {
        "document_id": RetrievalEntry.document_id,
        "id": RetrievalEntry.node_id,
        "user_id": RetrievalEntry.user_id,
    }
    if field_name not in columns:
        raise ValueError("unsupported retrieval cleanup field")
    if value is None or value == "":
        return
    if user_pk is not None:
        _validate_owner(user_pk)
    with database.SessionLocal() as db:
        _limits(db)
        statement = delete(RetrievalEntry).where(columns[field_name] == value)
        if user_pk is not None:
            statement = statement.where(RetrievalEntry.user_id == user_pk)
        db.execute(statement)
        db.commit()


def _validate_owner(user_pk: int) -> None:
    if type(user_pk) is not int or user_pk <= 0:
        raise ValueError("a trusted positive user_pk is required")


def _scope(user_pk: int, filters: dict[str, Any] | None):
    _validate_owner(user_pk)
    filters = dict(filters or {})
    if set(filters) - {"source_kind", "document_id"}:
        raise ValueError("unsupported retrieval scope filter")
    docs = filters.get("document_id")
    if isinstance(docs, str):
        docs = [docs]
    if docs is not None and (
        not isinstance(docs, (list, tuple, set, frozenset))
        or len(docs) > 1000
        or any(not isinstance(d, str) or not d or len(d) > 512 for d in docs)
    ):
        raise ValueError("invalid document scope")
    source = filters.get("source_kind")
    if source is not None and (not isinstance(source, str) or len(source) > 128):
        raise ValueError("invalid source kind")
    e, c, d, a = RetrievalEntry, DocumentChunk, KnowledgeDocument, FileAsset
    conditions = [
        e.generation == current_index_identity().fingerprint,
        e.user_id == user_pk,
        c.user_id == user_pk,
        d.user_id == user_pk,
        e.node_id == c.node_id,
        e.document_id == c.document_id,
        e.source_kind == c.source_kind,
        e.source_kind == d.source_kind,
        e.source_hash == c.text_hash,
        c.deleted_at.is_(None),
        c.index_status == "indexed",
        d.deleted_at.is_(None),
        d.status == "ready",
        d.index_fingerprint == e.generation,
        or_(
            d.file_asset_id.is_(None),
            and_(
                a.user_id == user_pk,
                a.deleted_at.is_(None),
                a.upload_status.in_(["uploaded", "consumed"]),
            ),
        ),
        d.conversation_id.is_(None),
        # Even an explicit document id is not an attachment capability. Private
        # attachments are grounded through their separately authorized reader.
        d.source_kind != "chat_attachment",
    ]
    if docs is not None:
        conditions.append(d.id.in_(sorted(docs)))
    if source is not None:
        conditions.append(d.source_kind == source)
    return (
        select(e)
        .join(c, e.chunk_id == c.id)
        .join(d, e.document_id == d.id)
        .outerjoin(a, d.file_asset_id == a.id)
        .where(*conditions)
    )


def _count_limit(top_k: int) -> int:
    if type(top_k) is not int or not 1 <= top_k <= 1000:
        raise ValueError("top_k must be between 1 and 1000")
    return top_k


def dense_search(
    *,
    query_dense: list[float],
    user_pk: int,
    top_k: int,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    top_k = _count_limit(top_k)
    identity = current_index_identity()
    vector = validate_vector(
        query_dense, expected_dim=identity.embedding_dim, label="查询"
    )
    # Materialize only the authorized current generation BEFORE vector distance.
    # Different dimension rows in other generations cannot enter the operator.
    scoped = _scope(user_pk, filters).cte("authorized").prefix_with("MATERIALIZED")
    metric = identity.similarity_metric
    if metric == "IP":
        distance = scoped.c.embedding.max_inner_product(vector)
        score = -distance
    elif metric == "COSINE":
        distance = scoped.c.embedding.cosine_distance(vector)
        score = 1 - distance
    elif metric == "L2":
        distance = scoped.c.embedding.l2_distance(vector)
        score = -distance
    else:
        raise ValueError("unsupported similarity metric")
    statement = (
        select(
            scoped.c.node_id.label("id"),
            scoped.c.passage.label("text"),
            scoped.c.user_id,
            scoped.c.source_kind,
            scoped.c.document_id,
            score.label("score"),
        )
        .order_by(distance, scoped.c.node_id)
        .limit(top_k)
    )
    with database.SessionLocal() as db:
        _limits(db)
        return [dict(row) for row in db.execute(statement).mappings()]


def sparse_search(
    *,
    query_text: str,
    user_pk: int,
    top_k: int,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """BM25 over the live, authorized corpus, never ts_rank mislabeled BM25."""
    top_k = _count_limit(top_k)
    wanted = sorted(term_counts(query_text, query=True))
    if not wanted:
        return []
    # Keep query construction in SQLAlchemy so scope and bound values cannot
    # drift from dense search. No vector or unrelated chunk body is materialized.
    e = RetrievalEntry
    corpus = (
        _scope(user_pk, filters)
        .with_only_columns(
            e.node_id,
            e.passage,
            e.user_id,
            e.source_kind,
            e.document_id,
            e.term_counts,
            e.token_count,
            e.lexical_terms,
        )
        .cte("authorized")
        .prefix_with("MATERIALIZED")
    )
    from sqlalchemy.dialects import postgresql

    # Compiling trusted SQLAlchemy AST with bound parameters is safe; user
    # strings remain parameters. This single scorer uses real corpus DF/avgdl.
    compiled = select(corpus).compile(
        dialect=postgresql.dialect(paramstyle="named"),
        compile_kwargs={"render_postcompile": True},
    )
    sql = str(compiled)
    # Embed the complete scoped SELECT as a subquery: its WITH clause remains
    # local and all metadata/owner conditions originate from _scope above.
    query = text(f"""
        WITH corpus AS MATERIALIZED ({sql}),
        terms AS (SELECT unnest(CAST(:wanted AS text[])) AS term),
        stats AS (SELECT count(*)::float8 AS n, greatest(coalesce(avg(token_count),1),1)::float8 AS avgdl FROM corpus),
        dfs AS (SELECT t.term, count(*)::float8 AS df FROM corpus c JOIN terms t ON c.term_counts ? t.term GROUP BY t.term),
        ranked AS (
            SELECT c.node_id, sum(
                ln(1 + (s.n - d.df + 0.5)/(d.df + 0.5))
                * ((c.term_counts ->> d.term)::float8 * (:k1 + 1))
                / ((c.term_counts ->> d.term)::float8 + :k1 * (1-:b+:b*c.token_count/s.avgdl))
            ) AS score
            FROM corpus c JOIN dfs d ON c.term_counts ? d.term CROSS JOIN stats s
            WHERE c.lexical_terms && CAST(:wanted AS text[])
            GROUP BY c.node_id
            ORDER BY score DESC, c.node_id LIMIT :top_k
        )
        SELECT c.node_id AS id, c.passage AS text, c.user_id, c.source_kind, c.document_id, r.score
        FROM ranked r JOIN corpus c ON c.node_id=r.node_id ORDER BY r.score DESC, c.node_id
    """)
    parameters = {
        **compiled.params,
        "wanted": wanted,
        "k1": BM25_K1,
        "b": BM25_B,
        "top_k": top_k,
    }
    with database.SessionLocal() as db:
        _limits(db)
        return [dict(row) for row in db.execute(query, parameters).mappings()]
