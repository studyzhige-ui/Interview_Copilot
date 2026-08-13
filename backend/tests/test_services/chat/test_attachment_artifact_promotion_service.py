"""Exact-scope promotion from a Conversation attachment to an Artifact."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import attachment_sources as attachment_sources_api
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.artifact import ArtifactResumeState, ArtifactVersion
from app.models.career_profile import CareerProfileDraftChange
from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.services import artifact_service
from app.schemas.artifact import ArtifactWriteInput
from app.services.chat.attachment_artifact_promotion_service import (
    promote_conversation_attachment_to_artifact,
)
from app.services.chat.attachment_source_service import (
    AttachmentSourceConflictError,
    AttachmentSourceNotFoundError,
)


def _user(db, name: str) -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(row)
    db.flush()
    return row


def _source(db, user: User, suffix: str):
    conversation = Conversation(
        id=f"conversation-{suffix}",
        user_id=user.id,
        title="Attachment promotion",
        type="general",
    )
    turn = ConversationTurn(
        id=f"turn-{suffix}",
        conversation_id=conversation.id,
        user_id=user.id,
        submission_id=f"submission-{suffix}",
        mode="agent",
        message="save this attachment",
    )
    checksum = suffix.encode().hex().ljust(64, "0")[:64]
    asset = FileAsset(
        id=f"fa-{suffix}",
        user_id=user.id,
        purpose="knowledge_document",
        original_filename=f"{suffix}.pdf",
        object_key=f"uploads/{user.id}/{suffix}/source.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/{suffix}/source.pdf",
        content_type="application/pdf",
        size_bytes=321,
        checksum_sha256=checksum,
        upload_status="uploaded",
        validation_status="passed",
    )
    document = KnowledgeDocument(
        id=f"doc-{suffix}",
        user_id=user.id,
        conversation_id=conversation.id,
        file_asset_id=asset.id,
        title=asset.original_filename,
        category="对话附件",
        source_kind="chat_attachment",
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status="ready",
        content_text="parsed projection must not be copied",
    )
    ref = ConversationAttachmentRef(
        id=f"caref-{suffix}",
        draft_id=f"draft-{suffix}",
        user_id=user.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        submission_id=turn.submission_id,
        position=0,
        file_asset_id=asset.id,
        source_document_id=document.id,
        file_asset_version=f"sha256:{checksum}",
        display_name=asset.original_filename,
    )
    db.add_all([conversation, asset])
    db.flush()
    db.add_all([turn, document])
    db.flush()
    db.add(ref)
    db.flush()
    return conversation, turn, asset, document, ref


def test_promotes_exact_file_version_without_copying_projection_and_replays(db_session):
    user = _user(db_session, "alice-promotion")
    conversation, _turn, asset, document, ref = _source(db_session, user, "report")

    first = promote_conversation_attachment_to_artifact(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        attachment_ref_id=ref.id,
        operation_key="promote-report",
        artifact_kind="interview_notes",
        title="面试复盘材料",
    )
    replay = promote_conversation_attachment_to_artifact(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        attachment_ref_id=ref.id,
        operation_key="promote-report",
        artifact_kind="interview_notes",
        title="面试复盘材料",
    )

    assert replay.artifact.id == first.artifact.id
    assert replay.current_version.id == first.current_version.id
    assert first.current_version.file_asset_id == asset.id
    assert first.current_version.file_asset_version == ref.file_asset_version
    assert first.current_version.content_text is None
    assert first.current_version.source_owner_type == "conversation_attachment_ref"
    assert first.current_version.source_owner_id == ref.id
    assert first.current_version.source_turn_id == ref.turn_id
    assert document.content_text == "parsed projection must not be copied"
    assert ref.removed_at is None
    assert asset.upload_status == "consumed"

    with pytest.raises(artifact_service.ArtifactConflictError):
        promote_conversation_attachment_to_artifact(
            db_session,
            user_pk=user.id,
            conversation_id=conversation.id,
            attachment_ref_id=ref.id,
            operation_key="promote-report",
            artifact_kind="interview_notes",
            title="changed payload",
        )


def test_regular_file_backed_artifact_also_freezes_current_asset_version(db_session):
    user = _user(db_session, "alice-file-version")
    _conversation_row, _turn, asset, _document, ref = _source(
        db_session, user, "plain-file"
    )

    artifact = artifact_service.save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="file-version-derived",
        artifact_kind="portfolio",
        version=ArtifactWriteInput(
            title="作品集",
            content_format="source_file",
            file_asset_id=asset.id,
        ),
    )
    replay = artifact_service.save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="file-version-derived",
        artifact_kind="portfolio",
        version=ArtifactWriteInput(
            title="作品集",
            content_format="source_file",
            file_asset_id=asset.id,
        ),
    )
    version = artifact_service.get_current_artifact_version(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )

    assert replay.id == artifact.id
    assert version.file_asset_version == ref.file_asset_version


def test_promotion_is_owner_scoped_and_rejects_stale_file_version(db_session):
    alice = _user(db_session, "alice-owner")
    bob = _user(db_session, "bob-owner")
    conversation, _turn, _asset, _document, ref = _source(db_session, alice, "owner")

    with pytest.raises(AttachmentSourceNotFoundError):
        promote_conversation_attachment_to_artifact(
            db_session,
            user_pk=bob.id,
            conversation_id=conversation.id,
            attachment_ref_id=ref.id,
            operation_key="cross-tenant",
            artifact_kind="portfolio",
            title="must not exist",
        )

    ref.file_asset_version = "sha256:stale"
    db_session.flush()
    with pytest.raises(AttachmentSourceConflictError):
        promote_conversation_attachment_to_artifact(
            db_session,
            user_pk=alice.id,
            conversation_id=conversation.id,
            attachment_ref_id=ref.id,
            operation_key="stale-version",
            artifact_kind="portfolio",
            title="stale",
        )


def test_resume_promotion_uses_resume_pipeline_without_silent_profile_write(db_session):
    user = _user(db_session, "alice-resume-promotion")
    conversation, _turn, _asset, _document, ref = _source(db_session, user, "resume")

    promoted = promote_conversation_attachment_to_artifact(
        db_session,
        user_pk=user.id,
        conversation_id=conversation.id,
        attachment_ref_id=ref.id,
        operation_key="promote-resume",
        artifact_kind="resume",
        title="后端工程师简历",
    )

    assert promoted.resume_record is not None
    assert promoted.artifact.kind == "resume"
    assert promoted.current_version.file_asset_version == ref.file_asset_version
    state = (
        db_session.query(ArtifactResumeState)
        .filter(ArtifactResumeState.artifact_id == promoted.artifact.id)
        .one_or_none()
    )
    assert state is not None and state.parse_status == "pending"
    assert state.parse_version_id == promoted.current_version.id
    assert db_session.query(CareerProfileDraftChange).count() == 0
    assert (
        db_session.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == promoted.artifact.id)
        .count()
        == 1
    )


def test_attachment_artifact_promotion_api_returns_frozen_identity(db_session):
    user = _user(db_session, "alice-promotion-api")
    conversation, _turn, _asset, _document, ref = _source(db_session, user, "api")
    app = FastAPI()
    app.include_router(attachment_sources_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/chat/{conversation.id}/attachment-sources/{ref.id}/artifact",
            json={
                "operation_key": "api-promotion",
                "artifact_kind": "portfolio",
                "title": "项目材料",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_id"] == ref.id
    assert body["file_asset_id"] == ref.file_asset_id
    assert body["file_asset_version"] == ref.file_asset_version
    assert body["resume_parse_dispatched"] is False
    version = body["artifact"]["current_version"]
    assert version["file_asset_id"] == ref.file_asset_id
    assert version["file_asset_version"] == ref.file_asset_version
    assert version["content_text"] is None
    assert version["source_owner_type"] == "conversation_attachment_ref"
    assert version["source_owner_id"] == ref.id
