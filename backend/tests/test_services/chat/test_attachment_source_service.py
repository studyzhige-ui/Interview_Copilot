"""Stage-1 source status, retry, promotion, and deletion contracts."""

from __future__ import annotations

import pytest

from app.models.chat import Conversation
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.interview_source import InterviewSourceRef
from app.models.knowledge import KnowledgeDocument
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.services.chat.attachment_ingress_service import (
    claim_attachment_drafts,
    create_attachment_draft,
)
from app.services.chat.attachment_source_service import (
    AttachmentSourceNotFoundError,
    cleanup_conversation_attachment_scope,
    cleanup_interview_source_scope,
    get_attachment_source_state,
    list_claimed_attachment_sources,
    list_debrief_project_sources,
    list_pending_submission_sources,
    load_debrief_source_text,
    mark_attachment_retry_dispatch_failed,
    prepare_attachment_projection_retry,
    promote_attachment_to_debrief,
    remove_failed_conversation_attachment,
    remove_debrief_project_source,
)


def _user(db, name: str = "alice") -> User:
    user = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    return user


def _record(db, user: User, record_id: str = "record-1") -> InterviewRecord:
    record = InterviewRecord(
        id=record_id,
        user_id=user.id,
        source="upload",
        title="Backend interview",
    )
    db.add(record)
    db.flush()
    return record


def _conversation(
    db,
    user: User,
    conversation_id: str,
    *,
    record: InterviewRecord | None = None,
) -> Conversation:
    conversation = Conversation(
        id=conversation_id,
        user_id=user.id,
        title=conversation_id,
        type="debrief" if record is not None else "general",
        subject_type="interview_record" if record is not None else None,
        subject_id=record.id if record is not None else None,
    )
    db.add(conversation)
    db.flush()
    return conversation


def _asset(db, user: User, asset_id: str) -> FileAsset:
    asset = FileAsset(
        id=asset_id,
        user_id=user.id,
        purpose="knowledge_document",
        original_filename=f"{asset_id}.pdf",
        object_key=f"uploads/{user.id}/{asset_id}/source.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/{asset_id}/source.pdf",
        content_type="application/pdf",
        size_bytes=123,
        checksum_sha256=asset_id.encode().hex().ljust(64, "0")[:64],
        upload_status="uploaded",
        validation_status="passed",
    )
    db.add(asset)
    db.flush()
    return asset


def _turn(
    db,
    user: User,
    conversation: Conversation,
    turn_id: str,
) -> ConversationTurn:
    turn = ConversationTurn(
        id=turn_id,
        conversation_id=conversation.id,
        user_id=user.id,
        submission_id=f"submission-{turn_id}",
        mode="agent",
        message="read the source",
    )
    db.add(turn)
    db.flush()
    return turn


def _claim(
    db,
    user: User,
    conversation: Conversation,
    asset: FileAsset,
    *,
    suffix: str,
) -> tuple[ConversationAttachmentDraft, ConversationAttachmentRef, KnowledgeDocument]:
    draft = create_attachment_draft(
        db,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        draft_id=f"draft-{suffix}",
    )
    turn = _turn(db, user, conversation, f"turn-{suffix}")
    [ref] = claim_attachment_drafts(
        db,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id=turn.submission_id,
        draft_ids=[draft.id],
    )
    document = db.get(KnowledgeDocument, draft.source_document_id)
    assert document is not None
    return draft, ref, document


def test_pending_and_claimed_sources_have_explicit_typed_status(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user, "conversation-status")
    queued_asset = _asset(db_session, user, "fa-queued")
    queued = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        file_asset_id=queued_asset.id,
        draft_id="draft-queued",
    )
    queued_document = db_session.get(KnowledgeDocument, queued.source_document_id)
    queued_document.status = "failed"
    queued_document.error_message = "OCR failed"
    submission = PendingSubmission(
        id="pending-with-source",
        conversation_id=conversation.id,
        user_id=user.id,
        version=1,
        position=1,
        status="failed",
        message="review",
        mode="agent",
        question_indexes_json=[],
        attachments_json=[{"draft_id": queued.id}],
        error="source failed",
    )
    db_session.add(submission)

    claimed_asset = _asset(db_session, user, "fa-claimed")
    _, claimed, claimed_document = _claim(
        db_session,
        user,
        conversation,
        claimed_asset,
        suffix="claimed",
    )
    claimed_document.status = "ready"
    claimed_document.content_text = "parsed content"
    db_session.flush()

    queued_states = list_pending_submission_sources(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        submission_id=submission.id,
    )
    claimed_states = list_claimed_attachment_sources(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        turn_id=claimed.turn_id,
    )

    assert [
        (item.source_kind, item.scope_kind, item.status) for item in queued_states
    ] == [("draft", "pending_submission", "failed")]
    assert queued_states[0].error_message == "OCR failed"
    assert queued_states[0].can_retry is True
    assert [
        (item.source_kind, item.scope_kind, item.status) for item in claimed_states
    ] == [("conversation_attachment", "conversation", "ready")]


def test_failed_projection_retry_reuses_identity_and_is_concurrency_idempotent(
    db_session,
):
    user = _user(db_session)
    conversation = _conversation(db_session, user, "conversation-retry")
    asset = _asset(db_session, user, "fa-retry")
    _, ref, document = _claim(
        db_session,
        user,
        conversation,
        asset,
        suffix="retry",
    )
    document.status = "failed"
    document.error_message = "parser crashed"
    original_document_id = document.id
    db_session.flush()

    first = prepare_attachment_projection_retry(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        source_id=ref.id,
    )
    second = prepare_attachment_projection_retry(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        source_id=ref.id,
    )

    assert first.should_dispatch is True
    assert second.should_dispatch is False
    assert first.state.source_id == ref.id
    assert first.state.document_id == original_document_id
    assert db_session.query(KnowledgeDocument).count() == 1
    assert db_session.query(ConversationAttachmentRef).count() == 1

    mark_attachment_retry_dispatch_failed(
        db_session,
        document_id=original_document_id,
        message="queue unavailable",
    )
    state = get_attachment_source_state(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        source_id=ref.id,
    )
    assert state.status == "failed"
    assert state.error_message == "queue unavailable"


def test_failed_claim_can_leave_scope_without_rewriting_frozen_identity(db_session):
    user = _user(db_session)
    conversation = _conversation(db_session, user, "conversation-remove-failed")
    asset = _asset(db_session, user, "fa-remove-failed")
    _draft, ref, document = _claim(
        db_session,
        user,
        conversation,
        asset,
        suffix="remove-failed",
    )
    turn = db_session.get(ConversationTurn, ref.turn_id)
    turn.status = "waiting"
    turn.waiting_reason = "attachment_parsing"
    conversation.active_turn_id = turn.id
    document.status = "failed"
    document.error_message = "unsupported page"
    frozen = (
        ref.id,
        ref.file_asset_id,
        ref.file_asset_version,
        ref.source_document_id,
        ref.position,
    )
    db_session.flush()

    removed, turn_id = remove_failed_conversation_attachment(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        attachment_ref_id=ref.id,
    )
    replay, replay_turn_id = remove_failed_conversation_attachment(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        attachment_ref_id=ref.id,
    )

    assert removed.removed_at is not None
    assert replay.id == removed.id
    assert turn_id == replay_turn_id == turn.id
    assert (
        ref.id,
        ref.file_asset_id,
        ref.file_asset_version,
        ref.source_document_id,
        ref.position,
    ) == frozen
    assert (
        list_claimed_attachment_sources(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
        )
        == []
    )


def test_explicit_promotion_shares_exact_source_across_debrief_conversations(
    db_session,
):
    user = _user(db_session)
    record = _record(db_session, user)
    origin = _conversation(db_session, user, "debrief-origin", record=record)
    sibling = _conversation(db_session, user, "debrief-sibling", record=record)
    other_record = _record(db_session, user, "record-other")
    foreign_scope = _conversation(
        db_session,
        user,
        "debrief-other",
        record=other_record,
    )
    asset = _asset(db_session, user, "fa-promoted")
    _, attachment_ref, document = _claim(
        db_session,
        user,
        origin,
        asset,
        suffix="promoted",
    )
    document.status = "ready"
    document.content_text = "exact promoted content"

    first = promote_attachment_to_debrief(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
        attachment_ref_id=attachment_ref.id,
    )
    retry = promote_attachment_to_debrief(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
        attachment_ref_id=attachment_ref.id,
    )
    db_session.flush()

    assert retry.id == first.id
    assert db_session.query(InterviewSourceRef).count() == 1
    assert document.conversation_id is None
    assert first.file_asset_id == attachment_ref.file_asset_id
    assert first.file_asset_version == attachment_ref.file_asset_version
    assert first.source_document_id == attachment_ref.source_document_id
    assert (
        list_debrief_project_sources(
            db_session,
            user_pk=user.id,
            interview_record_id=record.id,
        )[0].status
        == "ready"
    )
    loaded = load_debrief_source_text(
        db_session,
        user_pk=user.id,
        conversation_id=sibling.id,
        source_ref_id=first.id,
    )
    assert loaded["content"] == "exact promoted content"
    assert loaded["source"]["interview_record_id"] == record.id

    with pytest.raises(AttachmentSourceNotFoundError):
        load_debrief_source_text(
            db_session,
            user_pk=user.id,
            conversation_id=foreign_scope.id,
            source_ref_id=first.id,
        )


def test_scope_removal_does_not_remove_origin_conversation_attachment(db_session):
    user = _user(db_session)
    record = _record(db_session, user)
    origin = _conversation(db_session, user, "debrief-origin", record=record)
    asset = _asset(db_session, user, "fa-remove-scope")
    _, attachment_ref, document = _claim(
        db_session,
        user,
        origin,
        asset,
        suffix="remove-scope",
    )
    document.status = "ready"
    document.content_text = "kept in origin"
    promoted = promote_attachment_to_debrief(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
        attachment_ref_id=attachment_ref.id,
    )

    removed = remove_debrief_project_source(
        db_session,
        user_pk=user.id,
        interview_record_id=record.id,
        source_ref_id=promoted.id,
    )

    assert removed.removed_at is not None
    assert document.conversation_id == origin.id
    assert (
        list_debrief_project_sources(
            db_session,
            user_pk=user.id,
            interview_record_id=record.id,
        )
        == []
    )
    assert (
        list_claimed_attachment_sources(
            db_session,
            user_pk=user.id,
            conversation_id=origin.id,
        )[0].status
        == "ready"
    )


def test_conversation_cleanup_releases_local_sources_but_preserves_promoted_source(
    db_session,
):
    user = _user(db_session)
    record = _record(db_session, user)
    origin = _conversation(db_session, user, "debrief-delete", record=record)
    sibling = _conversation(db_session, user, "debrief-survivor", record=record)

    promoted_asset = _asset(db_session, user, "fa-delete-promoted")
    promoted_draft, promoted_ref, promoted_document = _claim(
        db_session,
        user,
        origin,
        promoted_asset,
        suffix="delete-promoted",
    )
    promoted_document.status = "ready"
    promoted_document.content_text = "survives origin deletion"
    promoted = promote_attachment_to_debrief(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
        attachment_ref_id=promoted_ref.id,
    )

    local_asset = _asset(db_session, user, "fa-delete-local")
    local_draft = create_attachment_draft(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
        file_asset_id=local_asset.id,
        draft_id="draft-delete-local",
    )
    local_document_id = local_draft.source_document_id
    pending = PendingSubmission(
        id="pending-delete-local",
        conversation_id=origin.id,
        user_id=user.id,
        version=1,
        position=1,
        status="pending",
        message="queued",
        mode="agent",
        question_indexes_json=[],
        attachments_json=[{"draft_id": local_draft.id}],
    )
    db_session.add(pending)
    db_session.flush()

    result = cleanup_conversation_attachment_scope(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
    )
    db_session.delete(origin)
    db_session.commit()

    assert result.pending_submissions == 1
    assert result.drafts == 2
    assert result.attachment_refs == 1
    assert result.deleted_projections == 1
    assert result.preserved_promoted_projections == 1
    assert result.deleted_file_assets == 1
    assert db_session.get(PendingSubmission, pending.id) is None
    assert db_session.get(ConversationAttachmentDraft, promoted_draft.id) is None
    assert db_session.get(ConversationAttachmentRef, promoted_ref.id) is None
    assert db_session.get(KnowledgeDocument, local_document_id) is None
    assert db_session.get(FileAsset, local_asset.id) is None
    assert db_session.get(InterviewSourceRef, promoted.id) is not None
    assert db_session.get(KnowledgeDocument, promoted_document.id) is not None
    assert db_session.get(FileAsset, promoted_asset.id) is not None
    assert (
        load_debrief_source_text(
            db_session,
            user_pk=user.id,
            conversation_id=sibling.id,
            source_ref_id=promoted.id,
        )["content"]
        == "survives origin deletion"
    )


def test_interview_scope_cleanup_releases_promoted_projection_after_conversations(
    db_session,
):
    user = _user(db_session)
    record = _record(db_session, user)
    origin = _conversation(db_session, user, "debrief-record-delete", record=record)
    asset = _asset(db_session, user, "fa-record-delete")
    _, attachment_ref, document = _claim(
        db_session,
        user,
        origin,
        asset,
        suffix="record-delete",
    )
    document.status = "ready"
    document.content_text = "temporary debrief source"
    promoted = promote_attachment_to_debrief(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
        attachment_ref_id=attachment_ref.id,
    )
    cleanup_conversation_attachment_scope(
        db_session,
        user_pk=user.id,
        conversation_id=origin.id,
    )
    db_session.delete(origin)
    db_session.flush()

    result = cleanup_interview_source_scope(
        db_session,
        user_pk=user.id,
        interview_record_id=record.id,
    )
    db_session.flush()

    assert result.source_refs == 1
    assert result.deleted_projections == 1
    assert result.deleted_file_assets == 1
    assert db_session.get(InterviewSourceRef, promoted.id) is None
    assert db_session.get(KnowledgeDocument, document.id) is None
    assert db_session.get(FileAsset, asset.id) is None
