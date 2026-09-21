"""Owned word-range playback, with separate read transactions around media I/O."""

from __future__ import annotations

from dataclasses import dataclass
import math

from app.core.command_errors import CommandError
from app.core.config import settings
from app.db.database import SessionLocal
from app.files.identity import file_asset_version_token
from app.local_inference.audio import SAMPLE_RATE
from app.media.application.playback_audio import MAX_CLIP_SECONDS, render_clip
from app.media.application.transcript_evidence import TranscriptEvidence
from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript


@dataclass(frozen=True)
class PlaybackSelection:
    transcript_id: str
    file_asset_id: str
    file_asset_version: str
    sha256: str
    storage_uri: str
    size_bytes: int | None
    first_sample: int
    last_sample: int


def select_playback(db, *, record_id, user_pk, command) -> PlaybackSelection:
    record = (
        db.query(InterviewRecord)
        .populate_existing()
        .filter_by(id=record_id, user_id=user_pk)
        .first()
    )
    if record is None:
        raise CommandError("not_found", "面试记录不存在")
    tr = (
        db.query(InterviewTranscript)
        .populate_existing()
        .filter_by(id=command.transcript_id, record_id=record_id, user_id=user_pk)
        .first()
    )
    if record.source != "upload" or tr is None or not tr.evidence_json:
        raise CommandError("not_found", "尚无可回放的词级录音证据")
    evidence = TranscriptEvidence.model_validate(tr.evidence_json)
    asset = (
        db.query(FileAsset)
        .populate_existing()
        .filter_by(id=evidence.audio.file_asset_id, user_id=user_pk)
        .first()
    )
    if (
        asset is None
        or asset.deleted_at is not None
        or asset.upload_status not in {"uploaded", "consumed"}
        or asset.validation_status != "passed"
    ):
        raise CommandError("not_found", "原录音不存在或已不可用")
    if (
        record.audio_file_asset_id != asset.id
        or asset.purpose != "interview_audio"
        or file_asset_version_token(asset) != evidence.audio.file_asset_version
        or (
            asset.checksum_sha256
            and asset.checksum_sha256.strip().lower() != evidence.audio.sha256
        )
    ):
        raise CommandError("conflict", "原录音版本已变化，请核对转写来源")
    indices = evidence.word_index()
    first, last = indices.get(command.first_word_id), indices.get(command.last_word_id)
    if first is None or last is None or not first <= last < first + 200:
        raise CommandError("invalid", "请选择同一转写版本内连续的 1–200 个词")
    words = evidence.words[first : last + 1]
    if any(w.start is None or w.end is None for w in words):
        raise CommandError("conflict", "所选词缺少原始时间证据，不能推测回放位置")
    start, end = min(w.start for w in words), max(w.end for w in words)
    if not (
        math.isfinite(start)
        and math.isfinite(end)
        and 0 <= start < end <= evidence.audio.duration_seconds
    ):
        raise CommandError("conflict", "原始词时间证据无效")
    first_sample, last_sample = (
        math.floor(start * SAMPLE_RATE),
        math.ceil(end * SAMPLE_RATE),
    )
    if last_sample - first_sample > MAX_CLIP_SECONDS * SAMPLE_RATE:
        raise CommandError("invalid", "请选择不超过 30 秒的片段")
    return PlaybackSelection(
        tr.id,
        asset.id,
        evidence.audio.file_asset_version,
        evidence.audio.sha256,
        asset.storage_uri,
        asset.size_bytes,
        first_sample,
        last_sample,
    )


def create_playback(*, record_id, user_pk, command):
    # Never hold a row lock or an open DB read transaction during storage/FFmpeg.
    with SessionLocal() as db:
        selection = select_playback(
            db, record_id=record_id, user_pk=user_pk, command=command
        )
    content = render_clip(
        selection,
        max_bytes=settings.USAGE_AUDIO_MAX_BYTES,
        max_ms=settings.USAGE_AUDIO_MAX_MS,
    )
    # Check again in a new transaction: deletion, ownership or reference changes
    # during the media read must prevent returning stale bytes. Historical
    # transcript versions remain playable when their exact source still exists.
    with SessionLocal() as db:
        current = select_playback(
            db, record_id=record_id, user_pk=user_pk, command=command
        )
        if current != selection:
            raise CommandError("conflict", "回放期间录音来源已变化，请重新核对")
    return selection, content
