"""Tests for document_chunk_service — the ``document_chunks`` fact source.

Parsed chunks live in the Postgres ``document_chunks`` table (not a LlamaIndex
docstore). ``read_document_text`` concatenates a document's LIVE chunks in order
(excluding soft-deleted ones); ``write_chunks`` persists nodes as ``indexed``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.models.document_chunk import DocumentChunk


def _seed(db, document_id, texts, user_id=1, **extra):
    for i, t in enumerate(texts):
        db.add(
            DocumentChunk(
                document_id=document_id,
                user_id=user_id,
                source_kind="user_upload",
                chunk_index=i,
                text=t,
                **extra,
            )
        )
    db.commit()


def test_read_document_text_concatenates_in_order(db_session):
    from app.rag.document_chunk_service import read_document_text

    _seed(
        db_session, "kdoc_1", ["孙根武\n北京邮电大学", "工作经历: Acme", "技能: Python"]
    )
    text, count = read_document_text(db_session, "kdoc_1")
    assert count == 3
    assert text.index("孙根武") < text.index("工作经历") < text.index("技能")


def test_read_document_text_empty_when_no_chunks(db_session):
    from app.rag.document_chunk_service import read_document_text

    text, count = read_document_text(db_session, "kdoc_missing")
    assert text == "" and count == 0


def test_read_document_text_truncates_at_max_chars(db_session):
    from app.rag.document_chunk_service import read_document_text

    _seed(db_session, "kdoc_big", ["A" * 30000])
    text, count = read_document_text(db_session, "kdoc_big", max_chars=100)
    assert len(text) == 100 and count == 1


def test_read_document_text_excludes_soft_deleted(db_session):
    """Soft-deleted chunks (deleted_at / index_status='deleted') are excluded
    immediately so a delete/update is reflected in reads at once."""
    from app.rag.document_chunk_service import read_document_text

    db_session.add_all(
        [
            DocumentChunk(
                document_id="kdoc_d",
                user_id=1,
                source_kind="user_upload",
                chunk_index=0,
                text="live one",
            ),
            DocumentChunk(
                document_id="kdoc_d",
                user_id=1,
                source_kind="user_upload",
                chunk_index=1,
                text="soft deleted",
                deleted_at=datetime.utcnow(),
            ),
            DocumentChunk(
                document_id="kdoc_d",
                user_id=1,
                source_kind="user_upload",
                chunk_index=2,
                text="marked deleted",
                index_status="deleted",
            ),
        ]
    )
    db_session.commit()
    text, count = read_document_text(db_session, "kdoc_d")
    assert count == 1
    assert "live one" in text
    assert "soft deleted" not in text and "marked deleted" not in text


def test_write_chunks_defaults_to_pending(db_session):
    """Two-phase write (§4.6.3): facts land as ``pending`` — the caller flips
    them to ``indexed`` only after the Milvus rows are written."""
    from app.rag.document_chunk_service import write_chunks

    nodes = [
        SimpleNamespace(text="chunk a", id_="n1"),
        SimpleNamespace(text="chunk b", id_="n2"),
    ]
    info = write_chunks(
        db_session,
        nodes=nodes,
        user_id=1,
        source_kind="user_upload",
        document_id="kdoc_w",
    )
    assert info["chunk_count"] == 2
    rows = (
        db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == "kdoc_w")
        .all()
    )
    assert len(rows) == 2
    assert all(r.index_status == "pending" for r in rows)
    assert all(r.text_hash for r in rows)


def test_mark_chunks_indexed_by_document_id(db_session):
    from app.rag.document_chunk_service import mark_chunks_indexed, write_chunks

    nodes = [SimpleNamespace(text="a", id_="n1"), SimpleNamespace(text="b", id_="n2")]
    write_chunks(
        db_session,
        nodes=nodes,
        user_id=1,
        source_kind="user_upload",
        document_id="kdoc_mi",
    )
    updated = mark_chunks_indexed(db_session, document_id="kdoc_mi")
    assert updated == 2
    rows = (
        db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == "kdoc_mi")
        .all()
    )
    assert all(r.index_status == "indexed" for r in rows)


def test_mark_chunks_indexed_by_node_ids_only_touches_pending(db_session):
    """The document-less path marks by node_id; a 'deleted' row is never
    resurrected (only 'pending' rows flip)."""
    from app.rag.document_chunk_service import mark_chunks_indexed

    db_session.add_all(
        [
            DocumentChunk(
                document_id=None,
                node_id="p1",
                user_id=1,
                source_kind="manual_text",
                chunk_index=0,
                text="pending one",
                index_status="pending",
            ),
            DocumentChunk(
                document_id=None,
                node_id="d1",
                user_id=1,
                source_kind="manual_text",
                chunk_index=1,
                text="already deleted",
                index_status="deleted",
            ),
        ]
    )
    db_session.commit()

    updated = mark_chunks_indexed(db_session, node_ids=["p1", "d1"])
    assert updated == 1  # only the pending one
    by_node = {r.node_id: r for r in db_session.query(DocumentChunk).all()}
    assert by_node["p1"].index_status == "indexed"
    assert by_node["d1"].index_status == "deleted"  # untouched


def test_write_chunks_persists_provenance_from_node_metadata(db_session):
    """page_start/page_end/token_count are lifted off each node's metadata
    (Phase B); a node without them leaves the columns NULL."""
    from app.rag.document_chunk_service import write_chunks

    nodes = [
        SimpleNamespace(
            text="with prov",
            id_="p1",
            metadata={
                "page_start": 2,
                "page_end": 3,
                "token_count": 96,
            },
        ),
        SimpleNamespace(text="no prov", id_="p2"),  # no metadata attr
    ]
    write_chunks(
        db_session,
        nodes=nodes,
        user_id=1,
        source_kind="user_upload",
        document_id="kdoc_prov",
    )
    rows = {
        r.node_id: r
        for r in db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == "kdoc_prov")
        .all()
    }
    assert (rows["p1"].page_start, rows["p1"].page_end, rows["p1"].token_count) == (
        2,
        3,
        96,
    )
    assert (rows["p2"].page_start, rows["p2"].page_end, rows["p2"].token_count) == (
        None,
        None,
        None,
    )


def test_write_chunks_builds_metadata_json_from_node_diagnostics(db_session):
    """metadata_json is per-chunk, built from the node's diagnostic keys;
    category is NEVER written there (it lives on knowledge_documents)."""
    import json
    from app.rag.document_chunk_service import write_chunks

    nodes = [
        SimpleNamespace(
            text="c1",
            id_="n1",
            metadata={
                "chunk_type": "text",
                "splitter_id": "markdown",
                "section_title": "缓存击穿",
                "heading_path": ["缓存", "异常"],
                "cleaning_profile": {"char_out": 2},
                "embedding_profile": {
                    "embedding_provider": "local",
                    "embedding_dim": 1024,
                },
                "parser_id": "pymupdf",
                "parser_profile": {"tier": "lightweight"},
                "ocr_used": False,  # a False boolean state must be kept (not dropped as null)
                "category": "面试题库",  # must NOT leak into metadata_json
                "user_id": 1,  # scope field, not diagnostic
            },
        ),
        SimpleNamespace(text="c2", id_="n2", metadata={}),  # no diagnostics
    ]
    write_chunks(
        db_session,
        nodes=nodes,
        user_id=1,
        source_kind="user_upload",
        document_id="kdoc_m",
    )
    rows = {
        r.node_id: r
        for r in db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == "kdoc_m")
        .all()
    }
    meta1 = json.loads(rows["n1"].metadata_json)
    assert meta1["chunk_type"] == "text"
    assert meta1["splitter_id"] == "markdown"
    assert meta1["section_title"] == "缓存击穿"
    assert meta1["heading_path"] == ["缓存", "异常"]
    assert meta1["cleaning_profile"] == {"char_out": 2}
    assert meta1["embedding_profile"] == {
        "embedding_provider": "local",
        "embedding_dim": 1024,
    }
    assert meta1["parser_id"] == "pymupdf"
    assert meta1["parser_profile"] == {"tier": "lightweight"}
    assert meta1["ocr_used"] is False  # False kept (is-not-None guard), not dropped
    assert "category" not in meta1  # INGEST-CLEANUP
    assert "user_id" not in meta1  # scope field, not a diagnostic
    # No diagnostics → NULL, not "{}".
    assert rows["n2"].metadata_json is None
