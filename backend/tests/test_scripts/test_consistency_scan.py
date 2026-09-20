"""Canonical projection drift checks; SQLite exercises SQL joins, not vector math."""

import hashlib
from app.models.knowledge import KnowledgeDocument
from app.models.document_chunk import DocumentChunk
from app.models.retrieval_index import RetrievalEntry, RetrievalGeneration
from app.rag.index.identity import current_index_identity
from scripts.consistency_scan import _retrieval_node_consistency


def seed(db):
    identity = current_index_identity()
    fp = identity.fingerprint
    db.add(
        RetrievalGeneration(
            fingerprint=fp,
            embedding_dim=identity.embedding_dim,
            identity_json=identity.to_dict(),
        )
    )
    for d in ["d1", "d2"]:
        db.add(
            KnowledgeDocument(
                id=d,
                user_id=1,
                title=d,
                source_kind="manual_text",
                status="ready",
                index_fingerprint=fp,
            )
        )
    db.flush()
    chunks = []
    for i in range(3):
        c = DocumentChunk(
            document_id="d1" if i < 2 else "d2",
            node_id=f"n{i}",
            user_id=1,
            source_kind="manual_text",
            chunk_index=i,
            text="hello",
            text_hash=hashlib.sha256(b"hello").hexdigest(),
            index_status="indexed",
        )
        db.add(c)
        db.flush()
        chunks.append(c)
        if i != 1:
            db.add(
                RetrievalEntry(
                    generation=fp,
                    chunk_id=c.id,
                    node_id=c.node_id,
                    document_id=c.document_id,
                    user_id=1,
                    source_kind=c.source_kind,
                    source_hash=c.text_hash,
                    passage="hello",
                    embedding=[0.1] * identity.embedding_dim,
                    term_counts={"hello": 1},
                    lexical_terms=["hello"],
                    token_count=1,
                )
            )
    db.commit()
    return chunks


def test_reports_missing_without_fetching_entire_projection(db_session):
    seed(db_session)
    findings = {f.name: f for f in _retrieval_node_consistency(db_session)}
    assert findings["missing_in_index"].count == 1 and findings[
        "missing_in_index"
    ].sample_ids == ["n1"]
    assert findings["stale_in_index"].count == findings["metadata_mismatch"].count == 0


def test_owner_mismatch_and_stale_document_reported(db_session):
    chunks = seed(db_session)
    db_session.get(DocumentChunk, chunks[0].id).user_id = 2
    db_session.get(KnowledgeDocument, "d2").status = "stale"
    db_session.commit()
    f = {f.name: f for f in _retrieval_node_consistency(db_session)}
    assert f["metadata_mismatch"].sample_ids == ["n0"]
    assert f["stale_in_index"].sample_ids == ["n2"]


def test_pending_or_old_generation_not_claimed_missing(db_session):
    chunks = seed(db_session)
    chunks[1].index_status = "pending"
    db_session.get(KnowledgeDocument, "d2").index_fingerprint = "older"
    db_session.commit()
    f = {f.name: f for f in _retrieval_node_consistency(db_session)}
    assert f["missing_in_index"].count == 0
    assert f["index_generation"].sample_ids == ["d2"]


def test_private_sources_are_not_a_global_rebuild_target(db_session):
    seed(db_session)
    db_session.get(KnowledgeDocument, "d1").source_kind = "chat_attachment"
    db_session.commit()
    f = {f.name: f for f in _retrieval_node_consistency(db_session)}
    assert f["missing_in_index"].count == 0
    assert "n0" in f["stale_in_index"].sample_ids
