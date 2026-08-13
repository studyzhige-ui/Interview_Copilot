from __future__ import annotations

from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.services.legacy_attachment_migration import migrate_legacy_attachments


def _asset(db, user: User, asset_id: str) -> FileAsset:
    row = FileAsset(
        id=asset_id,
        user_id=user.id,
        purpose="knowledge_document",
        original_filename=f"{asset_id}.pdf",
        object_key=f"uploads/{user.id}/{asset_id}/file.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/{asset_id}/file.pdf",
        upload_status="uploaded",
        validation_status="passed",
    )
    db.add(row)
    db.flush()
    return row


def _document(
    db,
    user: User,
    document_id: str,
    *,
    conversation_id: str | None,
    file_asset_id: str | None,
) -> KnowledgeDocument:
    row = KnowledgeDocument(
        id=document_id,
        user_id=user.id,
        conversation_id=conversation_id,
        file_asset_id=file_asset_id,
        title=f"{document_id}.pdf",
        source_kind="chat_attachment",
        status="ready",
    )
    db.add(row)
    db.flush()
    return row


def test_legacy_attachment_report_never_fabricates_scope(db_session):
    alice = User(username="legacy-attachment-alice", hashed_password="x")
    bob = User(username="legacy-attachment-bob", hashed_password="x")
    db_session.add_all([alice, bob])
    db_session.flush()
    conversation = Conversation(id="legacy-conv", user_id=alice.id)
    db_session.add(conversation)
    db_session.flush()

    canonical_asset = _asset(db_session, alice, "fa-canonical")
    orphan_asset = _asset(db_session, alice, "fa-orphan")
    foreign_asset = _asset(db_session, bob, "fa-foreign")
    canonical_document = _document(
        db_session,
        alice,
        "kdoc-canonical",
        conversation_id=conversation.id,
        file_asset_id=canonical_asset.id,
    )
    _document(
        db_session,
        alice,
        "kdoc-orphan",
        conversation_id=conversation.id,
        file_asset_id=orphan_asset.id,
    )
    _document(
        db_session,
        alice,
        "kdoc-owner-mismatch",
        conversation_id=conversation.id,
        file_asset_id=foreign_asset.id,
    )
    _document(
        db_session,
        alice,
        "kdoc-no-asset",
        conversation_id=conversation.id,
        file_asset_id=None,
    )
    turn = ConversationTurn(
        id="legacy-turn",
        conversation_id=conversation.id,
        user_id=alice.id,
        mode="agent",
        message="review the attached file",
    )
    db_session.add(turn)
    db_session.flush()
    db_session.add(
        ConversationAttachmentRef(
            id="ar-canonical",
            draft_id="legacy-draft-identity",
            user_id=alice.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="legacy-submission",
            position=0,
            file_asset_id=canonical_asset.id,
            source_document_id=canonical_document.id,
            file_asset_version=f"file_asset:{canonical_asset.id}",
            display_name=canonical_asset.original_filename,
        )
    )
    db_session.commit()

    dry_run = migrate_legacy_attachments(db_session, apply=False)
    assert dry_run["counts"] == {
        "already_migrated": 1,
        "quarantine_required": 3,
    }
    assert dry_run["items"][0]["canonical_targets"] == [
        {"kind": "conversation_attachment_ref", "id": "ar-canonical"}
    ]
    assert db_session.get(KnowledgeDocument, "kdoc-orphan").deleted_at is None
    assert db_session.query(ConversationAttachmentRef).count() == 1

    applied = migrate_legacy_attachments(db_session, apply=True)
    assert applied["counts"] == {"already_migrated": 1, "quarantined": 3}
    assert db_session.get(KnowledgeDocument, "kdoc-canonical").deleted_at is None
    assert db_session.get(KnowledgeDocument, "kdoc-orphan").deleted_at is not None
    assert db_session.get(FileAsset, orphan_asset.id) is not None
    assert db_session.query(ConversationAttachmentRef).count() == 1

    repeated = migrate_legacy_attachments(db_session, apply=True)
    assert repeated["counts"] == {
        "already_migrated": 1,
        "already_quarantined": 3,
    }
