"""Operator-provisioned HNSW graphs isolated by owner and generation.

Variable-width projections require expression/partial indexes. Requests never
perform DDL. Preparing graphs does not change source facts or embedding identity.
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import text

from app.core.config import settings

OPS = {"IP": "vector_ip_ops", "COSINE": "vector_cosine_ops", "L2": "vector_l2_ops"}


def index_spec(identity, user_pk):
    if type(user_pk) is not int or user_pk <= 0:
        raise ValueError("a trusted positive user_pk is required")
    if not re.fullmatch("[0-9a-f]{64}", identity.fingerprint):
        raise ValueError("invalid generation fingerprint")
    dim = identity.embedding_dim
    if type(dim) is not int or not 1 <= dim <= 2000:
        raise ValueError("HNSW vector indexes require 1..2000 dimensions")
    op = OPS[identity.similarity_metric]
    m, ef = settings.PGVECTOR_HNSW_M, settings.PGVECTOR_HNSW_EF_CONSTRUCTION
    if not 2 <= m <= 100 or not 2 * m <= ef <= 1000:
        raise ValueError("invalid HNSW construction parameters")
    contract = f"{identity.fingerprint}:{user_pk}:{dim}:{op}:{m}:{ef}"
    name = "ix_rag_hnsw_" + hashlib.sha256(contract.encode()).hexdigest()[:40]
    # Interpolation accepts only bounded numbers, validated digests and fixed ops.
    ddl = (
        f"CREATE INDEX {name} ON retrieval_entries USING hnsw "
        f"((embedding::vector({dim})) {op}) WITH (m={m}, ef_construction={ef}) "
        f"WHERE generation='{identity.fingerprint}' AND user_id={user_pk}"
    )
    return name, ddl


def require_version(db):
    version = db.execute(
        text("SELECT extversion FROM pg_extension WHERE extname='vector'")
    ).scalar()
    if version is None or tuple(int(n) for n in version.split(".")[:2]) < (0, 8):
        raise RuntimeError("HNSW iterative search requires pgvector >= 0.8")


def ready(db, identity, user_pk):
    name, _ = index_spec(identity, user_pk)
    return (
        db.execute(
            text("""
            SELECT i.indisvalid AND i.indisready AND am.amname='hnsw'
            FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
            JOIN pg_class t ON t.oid=i.indrelid
            JOIN pg_am am ON c.relam=am.oid
            WHERE c.relname=:name AND t.oid='retrieval_entries'::regclass
        """),
            {"name": name},
        ).scalar()
        is True
    )


def prepare(db, identity, user_pk):
    """Explicit maintenance transaction; serialize concurrent operator builds."""
    require_version(db)
    name, ddl = index_spec(identity, user_pk)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": name}
    )
    if not ready(db, identity, user_pk):
        db.execute(text(ddl))
    return name


def search_limits(db):
    require_version(db)
    for key, value in (
        ("hnsw.ef_search", settings.PGVECTOR_HNSW_EF_SEARCH),
        ("hnsw.iterative_scan", "strict_order"),
        ("hnsw.max_scan_tuples", settings.PGVECTOR_HNSW_MAX_SCAN_TUPLES),
    ):
        db.execute(
            text("SELECT set_config(:key, :value, true)"),
            {"key": key, "value": str(value)},
        )
