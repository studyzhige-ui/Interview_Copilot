"""Focused Artifact/version ownership, immutability and submission tests."""

from __future__ import annotations

import pytest

from app.models.artifact import (
    Artifact,
    ArtifactJobRelation,
    ArtifactSubmissionSnapshot,
    ArtifactVersion,
    ImmutableArtifactRecordError,
)
from app.models.chat import Conversation, ConversationMessage
from app.models.file_asset import FileAsset
from app.models.user import User
from app.schemas.artifact import ArtifactProvenanceInput, ArtifactWriteInput
from app.services.artifact_service import (
    ArtifactArchivedError,
    ArtifactConflictError,
    ArtifactOwnershipError,
    ArtifactSourceUnavailableError,
    ArtifactSubmissionProofError,
    archive_artifact,
    deliver_flow_artifact,
    edit_artifact,
    get_current_artifact_version,
    list_artifact_job_relations,
    list_artifact_submissions,
    list_artifact_versions,
    promote_message_to_artifact,
    record_receipt_confirmed_submission,
    record_user_confirmed_submission,
    relate_artifact_to_job,
    save_artifact_explicitly,
)


def _user(db, name: str) -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(row)
    db.flush()
    return row


def _message(db, user: User, *, content: str, role: str = "assistant"):
    conversation = Conversation(user_id=user.id, title="artifact source")
    db.add(conversation)
    db.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role=role,
        content=content,
    )
    db.add(message)
    db.flush()
    return message


def _asset(db, user: User, asset_id: str) -> FileAsset:
    row = FileAsset(
        id=asset_id,
        user_id=user.id,
        purpose="agent_output",
        original_filename=f"{asset_id}.pdf",
        object_key=f"uploads/{user.id}/{asset_id}/file.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/{asset_id}/file.pdf",
        content_type="application/pdf",
        size_bytes=100,
        upload_status="uploaded",
        validation_status="passed",
    )
    db.add(row)
    db.flush()
    return row


def _allow_job(_db, user_pk: int, owner_type: str, owner_id: str) -> bool:
    return owner_type == "job_opportunity" and owner_id == f"job-{user_pk}"


def test_ordinary_answer_is_not_artifact_until_explicit_save(db_session):
    user = _user(db_session, "alice")
    _message(db_session, user, content="ordinary answer")

    assert db_session.query(Artifact).count() == 0
    artifact = save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="save-1",
        artifact_kind="report",
        version=ArtifactWriteInput(title="Saved report", content_text="report body"),
    )
    current = get_current_artifact_version(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )

    assert current.version_no == 1
    assert current.origin_kind == "explicit_save"
    assert db_session.query(ArtifactSubmissionSnapshot).count() == 0


def test_message_promotion_is_owned_snapshotted_and_idempotent(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")
    message = _message(db_session, alice, content="promote this exact answer")

    with pytest.raises(ArtifactSourceUnavailableError):
        promote_message_to_artifact(
            db_session,
            user_pk=bob.id,
            operation_key="promote-1",
            artifact_kind="report",
            title="Stolen",
            source_message_id=message.id,
        )

    artifact = promote_message_to_artifact(
        db_session,
        user_pk=alice.id,
        operation_key="promote-1",
        artifact_kind="report",
        title="Review report",
        source_message_id=message.id,
    )
    retry = promote_message_to_artifact(
        db_session,
        user_pk=alice.id,
        operation_key="promote-1",
        artifact_kind="report",
        title="Review report",
        source_message_id=message.id,
    )
    version = get_current_artifact_version(
        db_session,
        user_pk=alice.id,
        artifact_id=artifact.id,
    )

    assert retry.id == artifact.id
    assert version.content_text == "promote this exact answer"
    assert version.source_message_id == message.id
    with pytest.raises(ArtifactConflictError):
        promote_message_to_artifact(
            db_session,
            user_pk=alice.id,
            operation_key="promote-1",
            artifact_kind="report",
            title="Different title",
            source_message_id=message.id,
        )


def test_file_owner_and_flow_owner_are_enforced_without_source_registry(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")
    alice_asset = _asset(db_session, alice, "fa-alice-artifact")

    with pytest.raises(ArtifactSourceUnavailableError):
        save_artifact_explicitly(
            db_session,
            user_pk=bob.id,
            operation_key="save-file",
            artifact_kind="resume",
            version=ArtifactWriteInput(
                title="Resume",
                file_asset_id=alice_asset.id,
                content_format="pdf",
            ),
        )

    flow_input = ArtifactWriteInput(
        title="Interview review",
        content_text="flow result",
        provenance=ArtifactProvenanceInput(
            source_owner_type="interview_record",
            source_owner_id="ir-1",
        ),
    )
    with pytest.raises(ArtifactOwnershipError):
        deliver_flow_artifact(
            db_session,
            user_pk=alice.id,
            operation_key="flow-1",
            artifact_kind="report",
            version=flow_input,
            flow_owner_checker=lambda *_args: False,
        )

    artifact = deliver_flow_artifact(
        db_session,
        user_pk=alice.id,
        operation_key="flow-1",
        artifact_kind="report",
        version=flow_input,
        flow_owner_checker=lambda _db, pk, kind, identity: (
            pk == alice.id and kind == "interview_record" and identity == "ir-1"
        ),
    )
    version = get_current_artifact_version(
        db_session,
        user_pk=alice.id,
        artifact_id=artifact.id,
    )
    assert version.source_owner_type == "interview_record"
    assert version.source_owner_id == "ir-1"

    # A completed operation is frozen. Its identical transport retry remains
    # idempotent even if the source owner is no longer available afterwards.
    retry = deliver_flow_artifact(
        db_session,
        user_pk=alice.id,
        operation_key="flow-1",
        artifact_kind="report",
        version=flow_input,
        flow_owner_checker=lambda *_args: False,
    )
    assert retry.id == artifact.id


def test_edit_appends_immutable_version_and_current_is_latest(db_session):
    user = _user(db_session, "alice")
    artifact = save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="save-1",
        artifact_kind="cover_letter",
        version=ArtifactWriteInput(title="Letter", content_text="v1"),
    )
    first = get_current_artifact_version(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    second = edit_artifact(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
        operation_key="edit-1",
        version=ArtifactWriteInput(title="Letter", content_text="v2"),
    )
    retry = edit_artifact(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
        operation_key="edit-1",
        version=ArtifactWriteInput(title="Letter", content_text="v2"),
    )

    assert second.version_no == 2
    assert retry.id == second.id
    assert (
        get_current_artifact_version(
            db_session,
            user_pk=user.id,
            artifact_id=artifact.id,
        ).id
        == second.id
    )
    assert first.content_text == "v1"
    assert db_session.query(ArtifactVersion).count() == 2

    db_session.commit()
    first.content_text = "rewritten history"
    with pytest.raises(ImmutableArtifactRecordError):
        db_session.flush()
    db_session.rollback()


def test_submitted_snapshot_freezes_exact_version_after_later_edit(db_session):
    user = _user(db_session, "alice")
    confirmation = _message(
        db_session,
        user,
        content="I submitted version one",
        role="user",
    )
    artifact = save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="save-1",
        artifact_kind="resume",
        version=ArtifactWriteInput(title="Resume", content_text="v1"),
    )
    first = get_current_artifact_version(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    relation = relate_artifact_to_job(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
        job_opportunity_id=f"job-{user.id}",
        job_owner_checker=_allow_job,
    )
    snapshot = record_user_confirmed_submission(
        db_session,
        user_pk=user.id,
        operation_key="submitted-1",
        artifact_id=artifact.id,
        artifact_version_id=first.id,
        job_opportunity_id=f"job-{user.id}",
        confirmation_message_id=confirmation.id,
        job_owner_checker=_allow_job,
    )
    retry = record_user_confirmed_submission(
        db_session,
        user_pk=user.id,
        operation_key="submitted-1",
        artifact_id=artifact.id,
        artifact_version_id=first.id,
        job_opportunity_id=f"job-{user.id}",
        confirmation_message_id=confirmation.id,
        job_owner_checker=_allow_job,
    )
    second = edit_artifact(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
        operation_key="edit-after-submit",
        version=ArtifactWriteInput(title="Resume", content_text="v2"),
    )

    assert relation.artifact_id == artifact.id
    assert retry.id == snapshot.id
    assert snapshot.artifact_version_id == first.id
    assert snapshot.artifact_version_id != second.id
    assert db_session.query(ArtifactJobRelation).count() == 1

    versions = list_artifact_versions(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    relations = list_artifact_job_relations(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    submissions = list_artifact_submissions(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    assert [version.id for version in versions] == [second.id, first.id]
    assert [row.job_opportunity_id for row in relations] == [f"job-{user.id}"]
    assert submissions[0][0].id == snapshot.id
    assert submissions[0][1].id == first.id
    assert submissions[0][1].content_text == "v1"

    db_session.commit()
    snapshot.artifact_version_id = second.id
    with pytest.raises(ImmutableArtifactRecordError):
        db_session.flush()
    db_session.rollback()


def test_external_submission_requires_exact_receipt_readback(db_session):
    user = _user(db_session, "alice")
    artifact = save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="save-1",
        artifact_kind="cover_letter",
        version=ArtifactWriteInput(title="Letter", content_text="body"),
    )
    version = get_current_artifact_version(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )

    with pytest.raises(ArtifactSubmissionProofError):
        record_receipt_confirmed_submission(
            db_session,
            user_pk=user.id,
            operation_key="receipt-1",
            artifact_id=artifact.id,
            artifact_version_id=version.id,
            job_opportunity_id=f"job-{user.id}",
            receipt_owner_type="tool_result",
            receipt_owner_id="call-1",
            job_owner_checker=_allow_job,
            proof_checker=lambda *_args: False,
        )

    snapshot = record_receipt_confirmed_submission(
        db_session,
        user_pk=user.id,
        operation_key="receipt-1",
        artifact_id=artifact.id,
        artifact_version_id=version.id,
        job_opportunity_id=f"job-{user.id}",
        receipt_owner_type="tool_result",
        receipt_owner_id="call-1",
        job_owner_checker=_allow_job,
        proof_checker=lambda _db, pk, job, version_id, kind, owner_id: (
            pk == user.id
            and job == f"job-{user.id}"
            and version_id == version.id
            and kind == "tool_result"
            and owner_id == "call-1"
        ),
    )
    assert snapshot.basis == "external_receipt"
    assert snapshot.artifact_version_id == version.id


def test_archive_preserves_versions_submissions_and_file_asset(db_session):
    user = _user(db_session, "alice")
    confirmation = _message(db_session, user, content="submitted", role="user")
    asset = _asset(db_session, user, "fa-saved")
    artifact = save_artifact_explicitly(
        db_session,
        user_pk=user.id,
        operation_key="save-file",
        artifact_kind="resume",
        version=ArtifactWriteInput(
            title="Resume",
            file_asset_id=asset.id,
            content_format="pdf",
        ),
    )
    version = get_current_artifact_version(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    snapshot = record_user_confirmed_submission(
        db_session,
        user_pk=user.id,
        operation_key="submitted-file",
        artifact_id=artifact.id,
        artifact_version_id=version.id,
        job_opportunity_id=f"job-{user.id}",
        confirmation_message_id=confirmation.id,
        job_owner_checker=_allow_job,
    )
    original_asset_state = (asset.upload_status, asset.deleted_at, asset.storage_uri)

    first_archive = archive_artifact(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    retry_archive = archive_artifact(
        db_session,
        user_pk=user.id,
        artifact_id=artifact.id,
    )
    db_session.refresh(asset)

    assert first_archive.archived_at == retry_archive.archived_at
    assert db_session.get(ArtifactVersion, version.id) is not None
    assert db_session.get(ArtifactSubmissionSnapshot, snapshot.id) is not None
    assert (
        asset.upload_status,
        asset.deleted_at,
        asset.storage_uri,
    ) == original_asset_state
    assert (
        get_current_artifact_version(
            db_session,
            user_pk=user.id,
            artifact_id=artifact.id,
            include_archived=True,
        ).id
        == version.id
    )
    with pytest.raises(ArtifactArchivedError):
        edit_artifact(
            db_session,
            user_pk=user.id,
            artifact_id=artifact.id,
            operation_key="edit-archived",
            version=ArtifactWriteInput(title="Resume", content_text="new"),
        )
