"""Publishing evidence must still own the current, unchanged source asset."""

import pytest

from app.db.types import utc_now
from app.files.identity import file_asset_version_token
from app.interviews.application.interview_record_service import interview_record_service
from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript
from app.models.user import User
from tests.test_services.voice.test_transcript_evidence import _evidence


def seed_source(db_session):
    owner = User(username="evidence-owner", hashed_password="x")
    db_session.add(owner)
    db_session.flush()
    asset = FileAsset(
        user_id=owner.id,
        purpose="interview_audio",
        original_filename="interview.wav",
        object_key="test/evidence-source",
        storage_uri="test/evidence-source.wav",
        checksum_sha256="0" * 64,
        upload_status="uploaded",
        validation_status="passed",
    )
    db_session.add(asset)
    db_session.flush()
    record = InterviewRecord(
        user_id=owner.id, source="upload", audio_file_asset_id=asset.id
    )
    db_session.add(record)
    db_session.flush()
    evidence = _evidence()
    evidence.audio.file_asset_id = asset.id
    evidence.audio.file_asset_version = file_asset_version_token(asset)
    return record, asset, evidence


@pytest.fixture
def source(db_session):
    return seed_source(db_session)


def publish(db, record, evidence):
    return interview_record_service.set_transcript_evidence(
        record.id, evidence=evidence, provider="test-complete-provider", db=db
    )


def test_publication_records_actual_provider_and_bound_source(db_session, source):
    record, asset, evidence = source
    transcript_id = publish(db_session, record, evidence)
    saved = db_session.get(InterviewTranscript, transcript_id)
    assert saved.provider == "test-complete-provider"
    assert saved.evidence_json["audio"]["file_asset_id"] == asset.id
    assert record.transcript_id == transcript_id


@pytest.mark.parametrize(
    "change", ["version", "bytes", "reference", "owner", "deleted", "pending"]
)
def test_changed_source_cannot_publish_any_transcript(db_session, source, change):
    record, asset, evidence = source
    if change == "version":
        asset.checksum_sha256 = "1" * 64
    elif change == "bytes":
        evidence.audio.sha256 = "1" * 64
    elif change == "reference":
        evidence.audio.file_asset_id = "another-asset"
    elif change == "owner":
        stranger = User(username="evidence-stranger", hashed_password="x")
        db_session.add(stranger)
        db_session.flush()
        asset.user_id = stranger.id
    elif change == "deleted":
        asset.deleted_at = utc_now()
    else:
        asset.upload_status = "pending_upload"
    with pytest.raises(ValueError, match="source_superseded"):
        publish(db_session, record, evidence)
    assert db_session.query(InterviewTranscript).count() == 0
    assert record.transcript_id is None


def test_stale_result_does_not_replace_an_existing_transcript(db_session, source):
    record, asset, evidence = source
    current = publish(db_session, record, evidence)
    asset.checksum_sha256 = "1" * 64
    with pytest.raises(ValueError, match="source_superseded"):
        publish(db_session, record, evidence)
    assert db_session.query(InterviewTranscript).count() == 1
    assert record.transcript_id == current
