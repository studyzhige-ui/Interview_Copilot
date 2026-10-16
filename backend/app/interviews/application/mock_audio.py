"""Durable mock recording drafts, executed by the existing transcription queue."""

import io
import asyncio
import hashlib
import logging
from datetime import timedelta

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.file_asset import FileAsset
from app.models.mock_audio_transcription import MockAudioTranscription
from app.schemas.chat import MockAnswerAudioResp
from app.interviews.application import mock_flow, mock_runtime_service
from app.files.application.file_asset_service import (
    store_validated_file_asset,
    presigned_get_urls,
    mark_file_asset_consumed,
    enqueue_asset_blob_delete,
)

logger = logging.getLogger(__name__)
TASK_TIMEOUT_SECONDS = 1800
WORKER_LEASE_SECONDS = 60


def snapshot(db, record, row):
    db.refresh(row)
    deadline = utc_now() - timedelta(seconds=TASK_TIMEOUT_SECONDS)
    stale = utc_now() - timedelta(seconds=WORKER_LEASE_SECONDS)
    timed_out = row.status in {"queued", "transcribing"} and row.created_at < deadline
    disconnected = (
        row.status == "transcribing" and (row.heartbeat_at or row.started_at) < stale
    )
    if timed_out or disconnected:
        from sqlalchemy import func

        condition = (
            MockAudioTranscription.created_at < deadline
            if timed_out
            else func.coalesce(
                MockAudioTranscription.heartbeat_at, MockAudioTranscription.started_at
            )
            < stale
        )
        db.query(MockAudioTranscription).filter(
            MockAudioTranscription.record_id == row.record_id,
            MockAudioTranscription.request_id == row.request_id,
            MockAudioTranscription.status == row.status,
            condition,
        ).update(
            {
                MockAudioTranscription.status: "failed",
                MockAudioTranscription.error: (
                    "转写任务已超时，原录音已保留。"
                    if timed_out
                    else "语音服务连接已中断，原录音已保留，请明确重试。"
                ),
                MockAudioTranscription.completed_at: utc_now(),
            },
            synchronize_session=False,
        )
        db.commit()
        db.refresh(row)
    urls = presigned_get_urls(
        db,
        [row.audio_file_asset_id],
        owner_id=record.user_id,
        purpose="mock_audio_clip",
    )
    return MockAnswerAudioResp(
        request_id=row.request_id,
        question_message_id=row.question_message_id,
        status=row.status,
        text=row.text,
        audio_file_asset_id=row.audio_file_asset_id,
        audio_url=urls.get(row.audio_file_asset_id),
        error=row.error,
    )


def admit(
    db,
    *,
    record_id,
    username,
    request_id,
    question_message_id,
    contents,
    filename,
    content_type,
):
    record = mock_flow.get_owned_mock_record(db, record_id, username)
    if record is None:
        raise LookupError("模拟面试不存在")
    prior = db.get(MockAudioTranscription, (record_id, request_id))
    digest = hashlib.sha256(contents).hexdigest()
    if prior is not None:
        asset = db.get(FileAsset, prior.audio_file_asset_id)
        if (
            prior.question_message_id != question_message_id
            or asset.checksum_sha256 != digest
        ):
            raise ValueError("同一录音请求不能更改问题或音频")
        return snapshot(db, record, prior)
    asset = store_validated_file_asset(
        db,
        user_id=username,
        filename=filename,
        purpose="mock_audio_clip",
        file_obj=io.BytesIO(contents),
        content_type=content_type,
        size_bytes=len(contents),
    )
    record = mock_flow.get_owned_mock_record(db, record_id, username, for_update=True)
    runtime = mock_runtime_service.get_runtime_for_record(
        db, interview_record_id=record_id
    )
    prior = db.get(MockAudioTranscription, (record_id, request_id))
    if (
        prior is not None
        or runtime is None
        or runtime.current_question_message_id != question_message_id
    ):
        enqueue_asset_blob_delete(db, asset)
        db.delete(asset)
        db.commit()
        if prior is not None:
            original = db.get(FileAsset, prior.audio_file_asset_id)
            if (
                prior.question_message_id != question_message_id
                or original.checksum_sha256 != digest
            ):
                raise ValueError("同一录音请求不能更改问题或音频")
            return snapshot(db, record, prior)
        raise ValueError("面试问题已变化，请重新读取现场")
    row = MockAudioTranscription(
        record_id=record_id,
        request_id=request_id,
        question_message_id=question_message_id,
        audio_file_asset_id=asset.id,
    )
    db.add(row)
    mark_file_asset_consumed(db, asset)
    db.commit()
    return _dispatch(db, record, row)


def retry(db, *, record_id, username, request_id, new_request_id):
    record = mock_flow.get_owned_mock_record(db, record_id, username, for_update=True)
    if record is None:
        raise LookupError("模拟面试不存在")
    old = db.get(MockAudioTranscription, (record_id, request_id))
    if old is None:
        raise LookupError("录音任务不存在")
    prior = db.get(MockAudioTranscription, (record_id, new_request_id))
    if prior is not None:
        if (
            prior.audio_file_asset_id != old.audio_file_asset_id
            or prior.question_message_id != old.question_message_id
        ):
            raise ValueError("同一请求不能更改录音来源")
        db.commit()
        return snapshot(db, record, prior)
    runtime = mock_runtime_service.get_runtime_for_record(
        db, interview_record_id=record_id
    )
    asset = db.get(FileAsset, old.audio_file_asset_id)
    if (
        old.status != "failed"
        or runtime is None
        or runtime.current_question_message_id != old.question_message_id
    ):
        raise ValueError("当前录音状态或面试问题不可重试")
    if asset is None or asset.deleted_at is not None or asset.user_id != record.user_id:
        raise ValueError("原录音已不可用")
    row = MockAudioTranscription(
        record_id=record_id,
        request_id=new_request_id,
        question_message_id=old.question_message_id,
        audio_file_asset_id=asset.id,
    )
    db.add(row)
    db.commit()
    return _dispatch(db, record, row)


def _dispatch(db, record, row):
    from app.task_queue.dispatch import dispatch_mock_audio_transcription

    try:
        dispatch_mock_audio_transcription(row.record_id, row.request_id)
    except Exception:
        logger.exception("Could not dispatch mock recording %s", row.request_id)
        row.status, row.error, row.completed_at = (
            "failed",
            "转写任务未能发送，原录音已保留，请重试。",
            utc_now(),
        )
        db.commit()
    return snapshot(db, record, row)


async def _recognize(record_id, request_id, path, uri):
    from app.media.application.short_clip_transcription import transcribe_short_clip
    from app.core.storage import download_file_from_storage

    def pulse():
        with SessionLocal() as db:
            db.query(MockAudioTranscription).filter_by(
                record_id=record_id, request_id=request_id, status="transcribing"
            ).update({MockAudioTranscription.heartbeat_at: utc_now()})
            db.commit()

    async def heartbeat():
        while True:
            await asyncio.sleep(10)
            await asyncio.to_thread(pulse)

    task = asyncio.create_task(heartbeat())
    try:
        await asyncio.to_thread(
            download_file_from_storage, uri, path, max_bytes=25 * 1024 * 1024
        )
        return await transcribe_short_clip(path, language="zh")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def execute(record_id, request_id):
    from app.core.async_runtime import run_async
    from app.core.runtime_files import create_runtime_temp_file
    from app.core.error_messages import humanize_error
    from app.usage.runtime import scope
    from pathlib import Path

    with SessionLocal() as db:
        row = (
            db.query(MockAudioTranscription)
            .filter_by(record_id=record_id, request_id=request_id)
            .with_for_update()
            .one_or_none()
        )
        if row is None or row.status in {"completed", "failed"}:
            return
        if row.status == "transcribing":
            row.status, row.error, row.completed_at = (
                "failed",
                "转写执行已中断，原录音已保留，请明确重试。",
                utc_now(),
            )
            db.commit()
            return
        asset = db.get(FileAsset, row.audio_file_asset_id)
        if asset is None or asset.deleted_at is not None:
            row.status, row.error, row.completed_at = (
                "failed",
                "原录音已删除",
                utc_now(),
            )
            db.commit()
            return
        runtime = mock_runtime_service.get_runtime_for_record(
            db, interview_record_id=record_id
        )
        if (
            runtime is None
            or runtime.current_question_message_id != row.question_message_id
        ):
            row.status, row.error, row.completed_at = (
                "failed",
                "面试问题已变化，原录音已保留。",
                utc_now(),
            )
            db.commit()
            return
        owner, uri = asset.user_id, asset.storage_uri
        row.status, row.started_at = "transcribing", utc_now()
        row.heartbeat_at = row.started_at
        db.commit()
    path = create_runtime_temp_file(suffix=".audio")
    text, error = "", None
    try:
        with scope(owner, f"mock-audio:{record_id}:{request_id}"):
            text = run_async(_recognize(record_id, request_id, path, uri)).strip()
        if not text:
            error = "没有识别到有效语音，请回听原录音并检查输入设备。"
    except Exception as exc:
        logger.exception("Mock recording transcription failed: %s", request_id)
        error = f"转写失败：{humanize_error(exc)}"
    finally:
        Path(path).unlink(missing_ok=True)
    with SessionLocal() as db:
        row = (
            db.query(MockAudioTranscription)
            .filter_by(record_id=record_id, request_id=request_id)
            .with_for_update()
            .one_or_none()
        )
        if row is not None and row.status == "transcribing":
            row.text, row.error, row.status = (
                text,
                error,
                "failed" if error else "completed",
            )
            row.completed_at = utc_now()
            db.commit()
