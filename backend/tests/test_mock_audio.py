"""Recording admission, safe recovery and shared voice-worker ownership."""

import hashlib
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from app.interviews.application import mock_audio
from app.models.chat import Conversation
from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.mock_interview_runtime import MockInterviewRuntime
from app.models.mock_audio_transcription import MockAudioTranscription


@pytest.fixture
def recording(db, owners, monkeypatch):
    monkeypatch.setattr(db, "commit", db.flush)
    record = InterviewRecord(
        user_id=owners[0].id, source="mock", status="mock_in_progress"
    )
    conversation = Conversation(user_id=owners[0].id, type="mock_interview")
    db.add_all([record, conversation])
    db.flush()
    conversation.subject_id = record.id
    runtime = MockInterviewRuntime(
        interview_record_id=record.id,
        user_id=owners[0].id,
        conversation_id=conversation.id,
        current_stage_key="technical",
        current_question_message_id=12,
        plan_json={},
        interviewer_style="professional",
        target_question_count=15,
    )
    db.add(runtime)
    db.flush()
    dispatched = []
    from app.task_queue import dispatch

    monkeypatch.setattr(
        dispatch,
        "dispatch_mock_audio_transcription",
        lambda *args: dispatched.append(args),
    )

    def store(db, **kwargs):
        data = kwargs["file_obj"].read()
        asset = FileAsset(
            user_id=owners[0].id,
            purpose="mock_audio_clip",
            original_filename="voice.wav",
            object_key=uuid.uuid4().hex,
            storage_uri="local://test/voice.wav",
            upload_status="uploaded",
            validation_status="passed",
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )
        db.add(asset)
        db.flush()
        return asset

    monkeypatch.setattr(mock_audio, "store_validated_file_asset", store)
    monkeypatch.setattr(mock_audio, "presigned_get_urls", lambda *args, **kwargs: {})
    monkeypatch.setattr(mock_audio, "enqueue_asset_blob_delete", lambda *args: None)
    return record, owners[0], runtime, dispatched


def admit(db, record, owner, **kwargs):
    return mock_audio.admit(
        db,
        record_id=record.id,
        username=owner.username,
        request_id="a" * 36,
        question_message_id=12,
        contents=kwargs.get("contents", b"voice"),
        filename="voice.wav",
        content_type="audio/wav",
    )


def test_admission_replay_conflict_and_stale_question(db, recording):
    record, owner, runtime, dispatched = recording
    first = admit(db, record, owner)
    assert (
        first.status == "queued"
        and admit(db, record, owner).request_id == first.request_id
    )
    assert len(dispatched) == 1 and db.query(FileAsset).count() == 1
    with pytest.raises(ValueError, match="不能更改"):
        admit(db, record, owner, contents=b"different")
    runtime.current_question_message_id = 13
    with pytest.raises(ValueError, match="问题已变化"):
        mock_audio.admit(
            db,
            record_id=record.id,
            username=owner.username,
            request_id="b" * 36,
            question_message_id=12,
            contents=b"next",
            filename="voice.wav",
            content_type="audio/wav",
        )
    assert len(dispatched) == 1


def test_worker_completion_replay_and_interrupted_execution(db, recording, monkeypatch):
    record, owner, _, _ = recording
    admitted = admit(db, record, owner)

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(mock_audio, "SessionLocal", session)
    from app.core import storage, async_runtime
    from app.media.application import short_clip_transcription

    calls = []

    async def recognize(*args, **kwargs):
        calls.append(args)
        return "识别结果"

    monkeypatch.setattr(
        storage, "download_file_from_storage", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(short_clip_transcription, "transcribe_short_clip", recognize)
    import asyncio

    monkeypatch.setattr(async_runtime, "run_async", asyncio.run)
    mock_audio.execute(record.id, admitted.request_id)
    mock_audio.execute(record.id, admitted.request_id)
    row = db.get(MockAudioTranscription, (record.id, admitted.request_id))
    assert row.status == "completed" and row.text == "识别结果" and len(calls) == 1
    row.status = "transcribing"
    mock_audio.execute(record.id, admitted.request_id)
    assert row.status == "failed" and len(calls) == 1


@pytest.mark.asyncio
async def test_live_pcm_is_dispatched_to_voice_worker_with_its_owner(monkeypatch):
    from app.media.realtime.asr import LiveASR
    from app.local_inference.audio import decode_pcm
    from app.task_queue import dispatch
    from app.usage.runtime import scope

    sent, forgotten = [], []

    def send(payload, owner, operation):
        sent.append((decode_pcm(payload), owner, operation))
        return SimpleNamespace(
            get=lambda **kwargs: "实时文字", forget=lambda: forgotten.append(True)
        )

    monkeypatch.setattr(dispatch, "dispatch_live_audio", send)
    with scope(23, "live-test"):
        assert await LiveASR().window(b"\x01\x00" * 1000) == "实时文字"
    assert sent[0][0] == b"\x01\x00" * 1000 and sent[0][1] == 23 and forgotten == [True]


def test_solo_voice_worker_preloads_before_first_task(monkeypatch):
    from app.task_queue import celery_app as module

    loaded = []
    monkeypatch.setattr(
        module, "_worker_subscribes_to", lambda queue: queue == "transcription"
    )
    monkeypatch.setattr(
        module, "_ensure_worker_runtime", lambda **kwargs: loaded.append(kwargs)
    )
    pool = type("TaskPool", (), {"__module__": "celery.concurrency.solo"})()
    module.warm_solo_voice_worker(sender=SimpleNamespace(pool=pool))
    assert loaded == [{"voice": True}]


def test_audio_ingestion_uses_same_voice_worker(db, owners, monkeypatch):
    from app.models.knowledge import KnowledgeDocument
    from app.task_queue import dispatch

    asset = FileAsset(
        user_id=owners[0].id,
        purpose="interview_audio",
        original_filename="voice.wav",
        object_key="test-audio",
        storage_uri="local://test/voice.wav",
    )
    db.add(asset)
    db.flush()
    document = KnowledgeDocument(
        user_id=owners[0].id,
        file_asset_id=asset.id,
        title="Audio",
        source_kind="user_upload",
    )
    db.add(document)
    db.flush()

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(dispatch, "SessionLocal", session, raising=False)
    from app.db import database

    monkeypatch.setattr(database, "SessionLocal", session)
    sent = []
    monkeypatch.setattr(
        dispatch.celery_app, "send_task", lambda *args, **kwargs: sent.append(kwargs)
    )
    dispatch.dispatch_document_ingestion(document.id)
    assert sent[-1]["queue"] == "transcription"
    asset.purpose = "knowledge_document"
    db.flush()
    dispatch.dispatch_document_ingestion(document.id)
    assert sent[-1]["queue"] == "pipeline"


@pytest.mark.parametrize(
    "status,validation,deleted,allowed",
    [
        ("uploaded", "passed", False, True),
        ("consumed", "passed", False, True),
        ("pending_upload", "pending", False, False),
        ("failed", "failed", False, False),
        ("consumed", "failed", False, False),
        ("consumed", "passed", True, False),
    ],
)
def test_recording_submission_requires_validated_readable_original(
    monkeypatch, status, validation, deleted, allowed
):
    from app.api import file_assets
    from fastapi import HTTPException

    asset = SimpleNamespace(
        upload_status=status,
        validation_status=validation,
        deleted_at=1 if deleted else None,
        validation_error="invalid",
    )
    monkeypatch.setattr(file_assets, "ensure_uploaded", lambda db, value: value)
    if allowed:
        assert file_assets.require_readable_upload(None, asset, "录音") is asset
    else:
        with pytest.raises(HTTPException) as rejected:
            file_assets.require_readable_upload(None, asset, "录音")
        assert rejected.value.status_code == 400


def test_voice_lease_uses_heartbeat_and_retains_original_when_worker_disappears(
    db, recording
):
    from datetime import timedelta
    from app.db.types import utc_now

    record, owner, _, _ = recording
    admitted = admit(db, record, owner)
    row = db.get(MockAudioTranscription, (record.id, admitted.request_id))
    row.status = "transcribing"
    row.started_at = utc_now() - timedelta(seconds=90)
    row.heartbeat_at = utc_now()
    db.flush()
    assert mock_audio.snapshot(db, record, row).status == "transcribing"
    row.heartbeat_at = utc_now() - timedelta(seconds=61)
    db.flush()
    failed = mock_audio.snapshot(db, record, row)
    assert failed.status == "failed" and "中断" in failed.error
    assert failed.audio_file_asset_id == admitted.audio_file_asset_id
    assert db.get(FileAsset, failed.audio_file_asset_id) is not None
    retried = mock_audio.retry(
        db,
        record_id=record.id,
        username=owner.username,
        request_id=admitted.request_id,
        new_request_id="b" * 36,
    )
    assert (
        retried.status == "queued"
        and retried.audio_file_asset_id == failed.audio_file_asset_id
    )
    assert db.query(FileAsset).count() == 1
    assert (
        mock_audio.retry(
            db,
            record_id=record.id,
            username=owner.username,
            request_id=admitted.request_id,
            new_request_id="b" * 36,
        ).request_id
        == retried.request_id
    )
