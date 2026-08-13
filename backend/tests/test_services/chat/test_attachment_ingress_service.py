"""Focused contract tests for durable draft -> immutable AttachmentRef ingress."""

from __future__ import annotations

import pytest

from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.services.chat.attachment_ingress_service import (
    AttachmentAssetUnavailableError,
    AttachmentClaimConflictError,
    AttachmentDraftConflictError,
    AttachmentDraftUnavailableError,
    attachment_ref_snapshot,
    claim_attachment_drafts,
    create_attachment_draft,
    preflight_attachment_drafts,
    remove_attachment_draft,
)


def _user(db, name: str = "alice") -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(row)
    db.flush()
    return row


def _conversation(db, user: User, conversation_id: str = "conv-1") -> Conversation:
    row = Conversation(id=conversation_id, user_id=user.id, title="draft test")
    db.add(row)
    db.flush()
    return row


def _asset(
    db,
    user: User,
    asset_id: str,
    *,
    upload_status: str = "uploaded",
    validation_status: str = "passed",
    checksum: str | None = None,
) -> FileAsset:
    row = FileAsset(
        id=asset_id,
        user_id=user.id,
        purpose="knowledge_document",
        original_filename=f"{asset_id}.pdf",
        object_key=f"uploads/{user.id}/{asset_id}/file.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/{asset_id}/file.pdf",
        content_type="application/pdf",
        size_bytes=123,
        checksum_sha256=checksum,
        upload_status=upload_status,
        validation_status=validation_status,
    )
    db.add(row)
    db.flush()
    return row


def _turn(
    db,
    user: User,
    conversation: Conversation,
    turn_id: str = "turn-1",
) -> ConversationTurn:
    row = ConversationTurn(
        id=turn_id,
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="review this",
    )
    db.add(row)
    db.flush()
    return row


def test_draft_is_durable_ingress_only_not_history_or_rag(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    asset = _asset(db_session, user, "fa-draft")

    draft = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        draft_id="draft-client-1",
    )
    db_session.commit()

    assert db_session.get(ConversationAttachmentDraft, draft.id) is not None
    assert db_session.query(ConversationMessage).count() == 0
    projection = db_session.get(KnowledgeDocument, draft.source_document_id)
    assert projection is not None
    assert projection.status == "processing"
    assert projection.source_kind == "chat_attachment"
    assert projection.conversation_id is None
    assert db_session.query(ConversationAttachmentRef).count() == 0


def test_draft_creation_is_idempotent_and_rejects_identity_reuse(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    first_asset = _asset(db_session, user, "fa-first")
    second_asset = _asset(db_session, user, "fa-second")

    first = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=first_asset.id,
        draft_id="same-draft",
    )
    retry = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=first_asset.id,
        draft_id="same-draft",
    )
    assert retry.id == first.id
    assert db_session.query(ConversationAttachmentDraft).count() == 1

    with pytest.raises(AttachmentDraftConflictError):
        create_attachment_draft(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            file_asset_id=second_asset.id,
            draft_id="same-draft",
        )


def test_claim_freezes_ordered_asset_version_scope_without_rag_side_effects(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    first_asset = _asset(db_session, user, "fa-one", checksum="A" * 64)
    second_asset = _asset(db_session, user, "fa-two")
    first = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=first_asset.id,
        draft_id="draft-one",
    )
    second = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=second_asset.id,
        draft_id="draft-two",
    )
    turn = _turn(db_session, user, conversation)

    refs = claim_attachment_drafts(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="input-1",
        draft_ids=[second.id, first.id],
    )
    db_session.commit()

    assert [ref.file_asset_id for ref in refs] == [second_asset.id, first_asset.id]
    assert [ref.position for ref in refs] == [0, 1]
    assert refs[0].file_asset_version == f"file_asset:{second_asset.id}"
    assert refs[1].file_asset_version == f"sha256:{'a' * 64}"
    assert attachment_ref_snapshot(refs[0]) == {
        "attachment_ref_id": refs[0].id,
        "file_asset_id": second_asset.id,
        "document_id": refs[0].source_document_id,
        "file_asset_version": f"file_asset:{second_asset.id}",
        "title": second_asset.original_filename,
        "position": 0,
        "scope": {"kind": "conversation", "conversation_id": conversation.id},
    }
    assert db_session.query(ConversationMessage).count() == 0
    assert db_session.query(KnowledgeDocument).count() == 2
    assert all(
        row.conversation_id == conversation.id
        for row in db_session.query(KnowledgeDocument).all()
    )


def test_claim_retry_returns_same_refs_and_changed_payload_conflicts(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    asset_one = _asset(db_session, user, "fa-one")
    asset_two = _asset(db_session, user, "fa-two")
    draft_one = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset_one.id,
        draft_id="draft-one",
    )
    draft_two = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset_two.id,
        draft_id="draft-two",
    )
    turn = _turn(db_session, user, conversation)
    first = claim_attachment_drafts(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="input-1",
        draft_ids=[draft_one.id],
    )
    retry = claim_attachment_drafts(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="input-1",
        draft_ids=[draft_one.id],
    )
    assert [row.id for row in retry] == [row.id for row in first]
    assert db_session.query(ConversationAttachmentRef).count() == 1

    with pytest.raises(AttachmentClaimConflictError):
        claim_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="input-1",
            draft_ids=[draft_two.id],
        )

    with pytest.raises(AttachmentDraftUnavailableError):
        claim_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="input-2",
            draft_ids=[draft_one.id],
        )

    with pytest.raises(AttachmentDraftUnavailableError):
        remove_attachment_draft(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            draft_id=draft_one.id,
        )

    # AttachmentRef is the durable Interaction Record after claim.  Cleanup
    # of the transient draft cannot break an identical transport retry.
    db_session.delete(draft_one)
    db_session.flush()
    retry_after_draft_cleanup = claim_attachment_drafts(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="input-1",
        draft_ids=[draft_one.id],
    )
    assert [row.id for row in retry_after_draft_cleanup] == [row.id for row in first]


def test_draft_rejects_non_ready_asset_and_claim_rejects_removed_draft(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    pending_asset = _asset(
        db_session,
        user,
        "fa-pending",
        upload_status="pending_upload",
        validation_status="pending",
    )
    removed_asset = _asset(db_session, user, "fa-removed")
    with pytest.raises(AttachmentAssetUnavailableError):
        create_attachment_draft(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            file_asset_id=pending_asset.id,
            draft_id="draft-pending",
        )
    removed = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=removed_asset.id,
        draft_id="draft-removed",
    )
    remove_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        draft_id=removed.id,
    )
    turn = _turn(db_session, user, conversation)

    with pytest.raises(AttachmentDraftUnavailableError):
        claim_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="input-removed",
            draft_ids=[removed.id],
        )
    assert db_session.query(ConversationAttachmentRef).count() == 0


def test_remove_draft_is_idempotent_and_never_mutates_source_asset(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    asset = _asset(db_session, user, "fa-owned", checksum="b" * 64)
    draft = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        draft_id="draft-remove",
    )
    original_asset_state = (
        asset.upload_status,
        asset.validation_status,
        asset.deleted_at,
        asset.checksum_sha256,
    )

    first = remove_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        draft_id=draft.id,
    )
    retry = remove_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        draft_id=draft.id,
    )
    db_session.refresh(asset)

    assert first.removed_at is not None
    assert retry.removed_at == first.removed_at
    assert (
        asset.upload_status,
        asset.validation_status,
        asset.deleted_at,
        asset.checksum_sha256,
    ) == original_asset_state


def test_draft_and_claim_enforce_user_and_conversation_scope(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")
    alice_conversation = _conversation(db_session, alice, "alice-conv")
    bob_conversation = _conversation(db_session, bob, "bob-conv")
    asset = _asset(db_session, alice, "fa-alice")

    with pytest.raises(AttachmentAssetUnavailableError):
        create_attachment_draft(
            db_session,
            user_pk=bob.id,
            conversation_id=bob_conversation.id,
            file_asset_id=asset.id,
            draft_id="stolen",
        )

    draft = create_attachment_draft(
        db_session,
        user_pk=alice.id,
        conversation_id=alice_conversation.id,
        file_asset_id=asset.id,
        draft_id="owned",
    )
    bob_turn = _turn(db_session, bob, bob_conversation, "bob-turn")
    with pytest.raises(AttachmentDraftUnavailableError):
        claim_attachment_drafts(
            db_session,
            user_pk=bob.id,
            conversation_id=bob_conversation.id,
            turn_id=bob_turn.id,
            submission_id="bob-input",
            draft_ids=[draft.id],
        )


def test_claim_rejects_projection_rebound_to_different_asset(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    first = _asset(db_session, user, "fa-projection-owner")
    second = _asset(db_session, user, "fa-projection-other")
    draft = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=first.id,
    )
    turn = _turn(db_session, user, conversation)
    projection = db_session.get(KnowledgeDocument, draft.source_document_id)
    projection.file_asset_id = second.id
    db_session.flush()

    with pytest.raises(AttachmentAssetUnavailableError):
        claim_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="submission-projection-mismatch",
            draft_ids=[draft.id],
        )


def test_preflight_locks_and_validates_without_mutating_ingress(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    asset = _asset(db_session, user, "fa-preflight", checksum="c" * 64)
    draft = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        draft_id="draft-preflight",
    )
    projection = db_session.get(KnowledgeDocument, draft.source_document_id)
    projection.status = "failed"
    projection.error_message = "parser failed"
    before = (
        draft.removed_at,
        projection.conversation_id,
        projection.status,
        projection.error_message,
    )

    preflight_attachment_drafts(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        submission_id="submission-preflight",
        draft_ids=[draft.id],
    )

    assert db_session.query(ConversationAttachmentRef).count() == 0
    assert (
        draft.removed_at,
        projection.conversation_id,
        projection.status,
        projection.error_message,
    ) == before


def test_preflight_rejects_removed_claimed_and_rebound_sources(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user)
    first_asset = _asset(db_session, user, "fa-preflight-one")
    second_asset = _asset(db_session, user, "fa-preflight-two")

    removed = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=first_asset.id,
        draft_id="draft-preflight-removed",
    )
    remove_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        draft_id=removed.id,
    )
    with pytest.raises(AttachmentDraftUnavailableError):
        preflight_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            submission_id="submission-removed",
            draft_ids=[removed.id],
        )

    claimed = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=second_asset.id,
        draft_id="draft-preflight-claimed",
    )
    turn = _turn(db_session, user, conversation, "turn-preflight")
    claim_attachment_drafts(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="submission-claimed",
        draft_ids=[claimed.id],
    )
    with pytest.raises(AttachmentDraftUnavailableError):
        preflight_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            submission_id="submission-other",
            draft_ids=[claimed.id],
        )

    rebound_asset = _asset(db_session, user, "fa-preflight-rebound")
    rebound = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=rebound_asset.id,
        draft_id="draft-preflight-rebound",
    )
    rebound_projection = db_session.get(KnowledgeDocument, rebound.source_document_id)
    rebound_projection.file_asset_id = first_asset.id
    db_session.flush()
    with pytest.raises(AttachmentAssetUnavailableError):
        preflight_attachment_drafts(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            submission_id="submission-rebound",
            draft_ids=[rebound.id],
        )
