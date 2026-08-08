"""Tests for ``app.rag.chunk_hydration`` — the Postgres
hydrate + live-check step that turns Milvus node ids into fully-attributed
chunk dicts.

Covers rank-order preservation, the live check (only indexed chunks belonging
to ready documents), file-asset attribution and ``metadata_json`` parsing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.rag.chunk_hydration import hydrate_chunks
from sqlalchemy.orm import Session


@pytest.fixture
def db(db_session: Session) -> Session:
    """Alias the shared conftest ``db_session`` (savepoint-rollback sqlite)."""
    return db_session


def _seed_user(db: Session) -> int:
    user = User(username="alice", hashed_password="x")
    db.add(user)
    db.commit()
    return user.id


def _seed_doc(
    db: Session,
    user_id: int,
    *,
    with_file: bool = True,
    status: str = "ready",
    deleted_at: datetime | None = None,
    suffix: str = "1",
) -> KnowledgeDocument:
    asset = None
    if with_file:
        asset = FileAsset(
            user_id=user_id,
            purpose="knowledge_document",
            original_filename=f"redis-{suffix}.pdf",
            object_key=f"uploads/{user_id}/fa{suffix}/redis.pdf",
            storage_uri=f"s3://b/uploads/{user_id}/fa{suffix}/redis.pdf",
            content_type="application/pdf",
            size_bytes=1234,
        )
        db.add(asset)
        db.flush()
    doc = KnowledgeDocument(
        user_id=user_id,
        title=f"Redis 笔记 {suffix}",
        source_kind="user_upload",
        status=status,
        deleted_at=deleted_at,
        file_asset_id=asset.id if asset else None,
    )
    db.add(doc)
    db.commit()
    return doc


def _seed_chunk(
    db: Session,
    doc: KnowledgeDocument,
    user_id: int,
    node_id: str,
    *,
    text: str = "Redis 缓存雪崩可以通过过期时间随机化缓解。",
    index_status: str = "indexed",
    deleted_at: datetime | None = None,
    chunk_index: int = 0,
    metadata_json: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=doc.id,
        node_id=node_id,
        user_id=user_id,
        source_kind=doc.source_kind,
        chunk_index=chunk_index,
        text=text,
        text_hash=f"h-{node_id}",
        index_status=index_status,
        deleted_at=deleted_at,
        metadata_json=metadata_json,
        page_start=page_start,
        page_end=page_end,
    )
    db.add(chunk)
    db.commit()
    return chunk


def test_hydrate_preserves_input_order_and_attributes(db: Session):
    uid = _seed_user(db)
    doc = _seed_doc(db, uid)
    _seed_chunk(
        db,
        doc,
        uid,
        "n1",
        chunk_index=0,
        page_start=3,
        page_end=4,
        metadata_json=json.dumps(
            {
                "section_title": "异常场景",
                "heading_path": ["缓存", "异常场景"],
            }
        ),
    )
    _seed_chunk(db, doc, uid, "n2", chunk_index=1, text="缓存穿透是查询不存在的数据。")

    out = hydrate_chunks(db, ["n2", "n1"])

    # Rank order = input order, NOT db order.
    assert [c["node_id"] for c in out] == ["n2", "n1"]
    c1 = out[1]
    assert c1["chunk_id"].startswith("dch_")
    assert c1["document_title"] == "Redis 笔记 1"
    assert c1["file_name"] == "redis-1.pdf"
    assert c1["category"] == "默认"
    assert c1["source_kind"] == "user_upload"
    assert c1["chunk_index"] == 0
    assert c1["section_title"] == "异常场景"
    assert c1["heading_path"] == ["缓存", "异常场景"]
    assert c1["text"] == "Redis 缓存雪崩可以通过过期时间随机化缓解。"
    # Phase-B provenance columns now flow through hydration.
    assert c1["page_start"] == 3
    assert c1["page_end"] == 4


def test_hydrate_drops_dead_chunks_and_documents(db: Session):
    uid = _seed_user(db)
    live_doc = _seed_doc(db, uid, suffix="1")
    _seed_chunk(db, live_doc, uid, "n-live")
    _seed_chunk(db, live_doc, uid, "n-chunk-deleted", deleted_at=datetime.now(UTC))
    _seed_chunk(db, live_doc, uid, "n-index-deleted", index_status="deleted")
    deleting_doc = _seed_doc(
        db,
        uid,
        suffix="2",
        status="deleting",
        deleted_at=datetime.now(UTC),
    )
    _seed_chunk(db, deleting_doc, uid, "n-dead-doc")

    out = hydrate_chunks(
        db,
        ["n-live", "n-chunk-deleted", "n-index-deleted", "n-dead-doc", "n-ghost"],
    )
    assert [c["node_id"] for c in out] == ["n-live"]


def test_hydrate_drops_unready_chunk_and_document_states(db: Session):
    uid = _seed_user(db)
    doc = _seed_doc(db, uid)
    _seed_chunk(db, doc, uid, "n-failed", index_status="failed")
    _seed_chunk(db, doc, uid, "n-pending", index_status="pending")
    processing = _seed_doc(db, uid, status="processing", suffix="processing")
    _seed_chunk(db, processing, uid, "n-processing-doc")

    out = hydrate_chunks(db, ["n-failed", "n-pending", "n-processing-doc"])
    assert out == []


def test_hydrate_fileless_document(db: Session):
    """improved_qa docs have no FileAsset — file fields come back None."""
    uid = _seed_user(db)
    doc = _seed_doc(db, uid, with_file=False, suffix="3")
    _seed_chunk(db, doc, uid, "n-qa")

    out = hydrate_chunks(db, ["n-qa"])
    assert out[0]["file_name"] is None
    assert out[0]["document_title"] == "Redis 笔记 3"


def test_hydrate_malformed_metadata_json(db: Session):
    uid = _seed_user(db)
    doc = _seed_doc(db, uid)
    _seed_chunk(db, doc, uid, "n-bad-meta", metadata_json="{not json")

    out = hydrate_chunks(db, ["n-bad-meta"])
    assert out[0]["section_title"] is None
    assert out[0]["heading_path"] is None


def test_hydrate_empty_input(db: Session):
    assert hydrate_chunks(db, []) == []
