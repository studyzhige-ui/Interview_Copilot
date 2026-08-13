from __future__ import annotations

import pytest

from app.models.agent_execution import AgentToolCall
from app.models.artifact import Artifact, ArtifactVersion
from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.outbox_job import OutboxJob
from app.models.user import User
from app.services.uploads.file_asset_deletion_service import (
    FileAssetDeletionConflictError,
    permanently_delete_file_asset,
    preview_file_asset_deletion,
)


def _fixture(db_session):
    user = User(username="permanent-file-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    asset = FileAsset(
        id="fa-permanent",
        user_id=user.id,
        purpose="knowledge_document",
        original_filename="private-resume.pdf",
        object_key=f"uploads/{user.id}/fa-permanent/private-resume.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/fa-permanent/private-resume.pdf",
        content_type="application/pdf",
        size_bytes=1234,
        checksum_sha256="a" * 64,
        upload_status="consumed",
        validation_status="passed",
    )
    conversation = Conversation(
        id="permanent-file-conversation",
        user_id=user.id,
        title="file",
        type="general",
    )
    db_session.add_all([asset, conversation])
    db_session.flush()
    document = KnowledgeDocument(
        id="kdoc-permanent",
        user_id=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title=asset.original_filename,
        category="附件",
        source_kind="chat_attachment",
        content_text="private parsed content",
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status="ready",
        chunk_count=1,
    )
    turn = ConversationTurn(
        id="permanent-file-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="chat",
        message="review",
        status="completed",
    )
    artifact = Artifact(
        id="artifact-permanent",
        user_id=user.id,
        kind="resume",
        creation_key="save-permanent",
    )
    db_session.add_all([document, turn, artifact])
    db_session.flush()
    ref = ConversationAttachmentRef(
        id="attachment-permanent",
        draft_id="draft-permanent",
        user_id=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id="submission-permanent",
        position=0,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version=f"sha256:{'a' * 64}",
        display_name=asset.original_filename,
    )
    version = ArtifactVersion(
        id="artifact-version-permanent",
        artifact_id=artifact.id,
        version_no=1,
        operation_key="save-permanent-v1",
        title="Resume",
        content_text=None,
        content_format="pdf",
        file_asset_id=asset.id,
        origin_kind="explicit_save",
    )
    chunk = DocumentChunk(
        id="chunk-permanent",
        document_id=document.id,
        user_id=user.id,
        source_kind="chat_attachment",
        chunk_index=0,
        text="private parsed content",
        index_status="indexed",
    )
    db_session.add_all([ref, version, chunk])
    db_session.flush()
    return user, asset, document, ref, version


def test_permanent_delete_revokes_scopes_erases_projection_and_keeps_history_refs(
    db_session,
):
    user, asset, document, ref, version = _fixture(db_session)
    impact = preview_file_asset_deletion(
        db_session,
        user_pk=user.id,
        file_asset_id=asset.id,
    )
    assert {item.reference_type for item in impact.reference_impacts} >= {
        "conversation_attachment",
        "parsing_projection",
        "artifact_version",
    }

    execution = permanently_delete_file_asset(
        db_session,
        user_pk=user.id,
        file_asset_id=asset.id,
        confirmation_token=impact.confirmation_token,
        confirm_file_asset_id=asset.id,
        confirm_filename=asset.original_filename,
    )
    db_session.commit()

    db_session.refresh(asset)
    db_session.refresh(document)
    db_session.refresh(ref)
    assert execution.result.status == "delete_pending"
    assert asset.deleted_at is not None
    assert asset.upload_status == "delete_pending"
    assert ref.removed_at is not None
    assert document.deleted_at is not None
    assert document.content_text is None
    assert (
        db_session.query(DocumentChunk).filter_by(document_id=document.id).count() == 0
    )
    assert db_session.get(ArtifactVersion, version.id).file_asset_id == asset.id
    delete_job = (
        db_session.query(OutboxJob)
        .filter_by(job_type="delete_object", aggregate_id=asset.id)
        .one()
    )
    assert delete_job.payload_json["storage_uri"] == asset.storage_uri


def test_permanent_delete_requires_exact_filename_confirmation(db_session):
    user, asset, *_ = _fixture(db_session)
    impact = preview_file_asset_deletion(
        db_session,
        user_pk=user.id,
        file_asset_id=asset.id,
    )
    with pytest.raises(FileAssetDeletionConflictError):
        permanently_delete_file_asset(
            db_session,
            user_pk=user.id,
            file_asset_id=asset.id,
            confirmation_token=impact.confirmation_token,
            confirm_file_asset_id=asset.id,
            confirm_filename="similar-name.pdf",
        )


def test_permanent_delete_requires_new_preview_after_external_transmission(
    db_session,
):
    user, asset, *_ = _fixture(db_session)
    impact = preview_file_asset_deletion(
        db_session,
        user_pk=user.id,
        file_asset_id=asset.id,
    )
    db_session.add(
        AgentToolCall(
            call_id="send-file-after-preview",
            turn_id="permanent-file-turn",
            session_id="permanent-file-conversation",
            user_id=user.id,
            tool_name="send_email",
            effect="external_write",
            arguments_json={"file_asset_id": asset.id},
            timeout_seconds=30,
            status="completed",
            dispatch_generation=1,
            policy_decision="allow",
            policy_reason="confirmed",
            result_json={"receipt_id": "provider-receipt"},
        )
    )
    db_session.flush()

    with pytest.raises(FileAssetDeletionConflictError):
        permanently_delete_file_asset(
            db_session,
            user_pk=user.id,
            file_asset_id=asset.id,
            confirmation_token=impact.confirmation_token,
            confirm_file_asset_id=asset.id,
            confirm_filename=asset.original_filename,
        )

    refreshed = preview_file_asset_deletion(
        db_session,
        user_pk=user.id,
        file_asset_id=asset.id,
    )
    assert refreshed.known_external_transmission_count == 1
    assert refreshed.confirmation_token != impact.confirmation_token
