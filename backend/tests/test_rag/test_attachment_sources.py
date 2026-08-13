"""Focused identity and readiness tests for Conversation attachment reads."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.agent_runtime.tools.file_tool import ReadFileArgs
from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.interview_record import InterviewRecord
from app.models.interview_source import InterviewSourceRef
from app.models.user import User
from app.rag.application import attachment_sources
from app.rag.application.attachment_sources import (
    AttachmentParsingPendingError,
    AttachmentSourceUnavailableError,
    load_attachment_sources,
    load_attachment_text,
    load_debrief_source_text,
)
from app.rag.grounding.builder import GroundingBuilder


def _seed_attachment(db, *, status: str = "ready") -> dict[str, object]:
    user = User(username="attachment-reader", hashed_password="x")
    db.add(user)
    db.flush()
    conversation = Conversation(
        id="conv-attachment-read",
        user_id=user.id,
        title="attachment read",
    )
    db.add(conversation)
    db.flush()
    turn = ConversationTurn(
        id="turn-attachment-read",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="read it",
    )
    asset = FileAsset(
        id="fa-attachment-read",
        user_id=user.id,
        purpose="knowledge_document",
        original_filename="notes.txt",
        object_key=f"uploads/{user.id}/fa-attachment-read/notes.txt",
        storage_uri=f"s3://bucket/uploads/{user.id}/fa-attachment-read/notes.txt",
        content_type="text/plain",
        size_bytes=12,
        checksum_sha256="abc123",
        upload_status="consumed",
        validation_status="passed",
    )
    document = KnowledgeDocument(
        id="kdoc-attachment-read",
        user_id=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title="notes.txt",
        category="会话附件",
        source_kind="chat_attachment",
        content_text="parsed attachment body",
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status=status,
    )
    ref = ConversationAttachmentRef(
        id="ar-attachment-read",
        draft_id="ad-attachment-read",
        user_id=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="submission-attachment-read",
        position=0,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version="sha256:abc123",
        display_name="notes.txt",
    )
    chunk = DocumentChunk(
        id="chunk-attachment-read",
        document_id=document.id,
        node_id="node-attachment-read",
        user_id=user.id,
        source_kind="chat_attachment",
        chunk_index=0,
        text="parsed attachment body",
        index_status="private",
    )
    db.add_all([turn, asset, document, ref, chunk])
    db.commit()
    return {
        "user": user,
        "conversation": conversation,
        "document": document,
        "ref": ref,
        "snapshot": {
            "attachment_ref_id": ref.id,
            "file_asset_id": asset.id,
            "file_asset_version": ref.file_asset_version,
            "title": ref.display_name,
            "position": 0,
            "scope": {
                "kind": "conversation",
                "conversation_id": conversation.id,
            },
        },
    }


def _patch_session(db_session, monkeypatch) -> None:
    maker = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(attachment_sources, "SessionLocal", maker)


def _add_conversation_source(
    db,
    seeded,
    *,
    suffix: str,
    title: str,
    content: str,
    status: str = "ready",
):
    user = seeded["user"]
    conversation = seeded["conversation"]
    turn = ConversationTurn(
        id=f"turn-{suffix}",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message=f"source {suffix}",
    )
    asset = FileAsset(
        id=f"fa-{suffix}",
        user_id=user.id,
        purpose="knowledge_document",
        original_filename=title,
        object_key=f"uploads/{user.id}/fa-{suffix}/{title}",
        storage_uri=f"s3://bucket/uploads/{user.id}/fa-{suffix}/{title}",
        content_type="text/plain",
        size_bytes=len(content),
        checksum_sha256=f"checksum-{suffix}",
        upload_status="consumed",
        validation_status="passed",
    )
    document = KnowledgeDocument(
        id=f"kdoc-{suffix}",
        user_id=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title=title,
        category="会话附件",
        source_kind="chat_attachment",
        content_text=content,
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status=status,
    )
    ref = ConversationAttachmentRef(
        id=f"ar-{suffix}",
        draft_id=f"ad-{suffix}",
        user_id=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id=f"submission-{suffix}",
        position=0,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version=f"sha256:checksum-{suffix}",
        display_name=title,
    )
    chunks = [
        DocumentChunk(
            id=f"chunk-{suffix}-{index}",
            document_id=document.id,
            node_id=f"node-{suffix}-{index}",
            user_id=user.id,
            source_kind="chat_attachment",
            chunk_index=index,
            text=f"{content} section {index}",
            index_status="private",
        )
        for index in range(12)
    ]
    db.add_all([turn, asset, document, ref, *chunks])
    db.commit()
    return ref, document, asset


def test_source_resolver_requires_ref_and_frozen_version(db_session, monkeypatch):
    seeded = _seed_attachment(db_session)
    _patch_session(db_session, monkeypatch)

    bundle = load_attachment_sources(
        user_id="attachment-reader",
        session_id="conv-attachment-read",
        query="attachment",
        explicit_attachments=(seeded["snapshot"],),
    )

    assert bundle.documents[0]["attachment_ref_id"] == "ar-attachment-read"
    assert bundle.result.chunks[0]["attachment_ref_id"] == "ar-attachment-read"
    assert "read_file(attachment_ref_id=...)" in bundle.manifest
    grounded = GroundingBuilder().build(bundle.result, token_budget=1000)
    assert grounded.sources[0]["attachment_ref_id"] == "ar-attachment-read"
    assert grounded.sources[0]["file_asset_id"] == "fa-attachment-read"
    assert grounded.sources[0]["file_asset_version"] == "sha256:abc123"

    forged = {**seeded["snapshot"], "file_asset_id": "fa-owner-wide-bypass"}
    with pytest.raises(AttachmentSourceUnavailableError) as exc_info:
        load_attachment_sources(
            user_id="attachment-reader",
            session_id="conv-attachment-read",
            query="attachment",
            explicit_attachments=(forged,),
        )
    assert exc_info.value.reason == "snapshot_mismatch"

    seeded["ref"].file_asset_version = "sha256:stale"
    db_session.commit()
    with pytest.raises(AttachmentSourceUnavailableError) as exc_info:
        load_attachment_text(
            user_id="attachment-reader",
            session_id="conv-attachment-read",
            attachment_ref_id="ar-attachment-read",
        )
    assert exc_info.value.reason == "version_mismatch"


def test_explicit_processing_attachment_never_silently_disappears(
    db_session, monkeypatch
):
    seeded = _seed_attachment(db_session, status="processing")
    _patch_session(db_session, monkeypatch)

    with pytest.raises(AttachmentParsingPendingError) as exc_info:
        load_attachment_sources(
            user_id="attachment-reader",
            session_id="conv-attachment-read",
            query="attachment",
            explicit_attachments=(seeded["snapshot"],),
        )
    assert exc_info.value.attachment_ref_ids == ("ar-attachment-read",)
    assert exc_info.value.document_ids == ("kdoc-attachment-read",)


def test_read_file_contract_has_no_owner_wide_upload_or_document_selector():
    assert set(ReadFileArgs.model_fields) == {
        "attachment_ref_id",
        "source_ref_id",
        "path",
        "offset",
        "limit",
    }


def test_history_selection_is_query_bounded_and_explicit_first(
    db_session,
    monkeypatch,
):
    seeded = _seed_attachment(db_session)
    relevant, _, _ = _add_conversation_source(
        db_session,
        seeded,
        suffix="python-architecture",
        title="python-architecture.txt",
        content="Python service architecture and database boundaries",
    )
    _add_conversation_source(
        db_session,
        seeded,
        suffix="cooking",
        title="cooking.txt",
        content="tomato soup recipe",
    )
    stale, _, _ = _add_conversation_source(
        db_session,
        seeded,
        suffix="python-stale",
        title="python-stale.txt",
        content="Python stale source",
    )
    stale.file_asset_version = "sha256:no-longer-current"
    db_session.commit()
    _patch_session(db_session, monkeypatch)

    bundle = load_attachment_sources(
        user_id="attachment-reader",
        session_id="conv-attachment-read",
        query="compare Python architecture",
        explicit_attachments=(seeded["snapshot"],),
    )

    assert bundle.documents[0]["attachment_ref_id"] == "ar-attachment-read"
    assert bundle.documents[0]["selection"] == "explicit"
    assert bundle.documents[1]["attachment_ref_id"] == relevant.id
    assert all(
        item.get("attachment_ref_id") != "ar-cooking" for item in bundle.documents
    )
    assert all(item.get("attachment_ref_id") != stale.id for item in bundle.documents)
    assert bundle.result.diagnostics["historical_selected_count"] == 1
    historical_chunks = [
        chunk
        for chunk in bundle.result.chunks
        if chunk.get("attachment_ref_id") == relevant.id
    ]
    assert len(historical_chunks) == 8


def test_debrief_selects_only_same_record_source_and_supports_typed_full_read(
    db_session,
    monkeypatch,
):
    seeded = _seed_attachment(db_session)
    user = seeded["user"]
    conversation = seeded["conversation"]
    record = InterviewRecord(
        user_id=user.id, source="upload", title="Backend interview"
    )
    other_record = InterviewRecord(user_id=user.id, source="upload", title="Other")
    db_session.add_all([record, other_record])
    db_session.flush()
    conversation.type = "debrief"
    conversation.subject_type = "interview_record"
    conversation.subject_id = record.id
    _ref, document, asset = _add_conversation_source(
        db_session,
        seeded,
        suffix="system-design",
        title="system-design-notes.txt",
        content="system design bottleneck and cache tradeoffs",
    )
    promoted = InterviewSourceRef(
        id="isr-system-design",
        interview_record_id=record.id,
        user_id=user.id,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version="sha256:checksum-system-design",
        display_name="system-design-notes.txt",
        origin_conversation_id=conversation.id,
        origin_attachment_ref_id="ar-system-design",
    )
    wrong_scope = InterviewSourceRef(
        id="isr-wrong-record",
        interview_record_id=other_record.id,
        user_id=user.id,
        file_asset_id=seeded["ref"].file_asset_id,
        source_document_id=seeded["document"].id,
        file_asset_version=seeded["ref"].file_asset_version,
        display_name="wrong-record.txt",
        origin_conversation_id=conversation.id,
        origin_attachment_ref_id=seeded["ref"].id,
    )
    db_session.add_all([promoted, wrong_scope])
    db_session.commit()
    _patch_session(db_session, monkeypatch)

    bundle = load_attachment_sources(
        user_id="attachment-reader",
        session_id=conversation.id,
        query="review system design cache bottleneck",
    )
    selected_ids = {item.get("source_ref_id") for item in bundle.documents}
    assert promoted.id in selected_ids
    assert wrong_scope.id not in selected_ids
    selected = next(item for item in bundle.documents if item.get("source_ref_id"))
    assert selected["scope"] == "debrief_project"
    assert selected["selection"] == "query_selected"

    full = load_debrief_source_text(
        user_id="attachment-reader",
        session_id=conversation.id,
        source_ref_id=promoted.id,
    )
    assert full["interview_record_id"] == record.id
    assert "cache tradeoffs" in full["content"]
    with pytest.raises(AttachmentSourceUnavailableError):
        load_debrief_source_text(
            user_id="attachment-reader",
            session_id=conversation.id,
            source_ref_id=wrong_scope.id,
        )
