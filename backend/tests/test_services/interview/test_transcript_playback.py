"""Owned version-bound playback through real FFmpeg, without models or cloud."""

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import io
from types import SimpleNamespace
import wave

import pytest

from app.core.command_errors import CommandError
from app.db.types import utc_now
from app.interviews.application import transcript_playback as service
from app.media.application import playback_audio
from app.models.file_asset import FileAsset
from app.schemas.transcript_correction import TranscriptPlaybackRequest
from tests.test_services.interview.test_transcript_corrections import seed


@pytest.fixture
def audio_data(db_session, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    owner, stranger, record, tr, _ = seed(db_session)
    path = tmp_path / "interview.wav"
    pcm = b"".join(
        (i % 32767).to_bytes(2, "little", signed=True) for i in range(48_000)
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(pcm)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = FileAsset(
        id="fa_playback",
        user_id=owner.id,
        purpose="interview_audio",
        original_filename="interview.wav",
        object_key="owned/interview.wav",
        storage_uri="local://interview.wav",
        size_bytes=path.stat().st_size,
        checksum_sha256=digest,
        upload_status="consumed",
        validation_status="passed",
    )
    db_session.add(asset)
    record.audio_file_asset_id = asset.id
    evidence = dict(tr.evidence_json)
    evidence["audio"] = {
        **evidence["audio"],
        "file_asset_id": asset.id,
        "file_asset_version": f"sha256:{digest}",
        "sha256": digest,
    }
    tr.evidence_json = evidence
    db_session.commit()
    command = TranscriptPlaybackRequest(
        transcript_id=tr.id, first_word_id="w000004", last_word_id="w000005"
    )
    return SimpleNamespace(
        owner=owner,
        stranger=stranger,
        record=record,
        tr=tr,
        asset=asset,
        command=command,
        path=path,
        pcm=pcm,
    )


def selection(db, data, command=None, user=None):
    return service.select_playback(
        db,
        record_id=data.record.id,
        user_pk=user or data.owner.id,
        command=command or data.command,
    )


def test_owned_clip_has_exact_source_samples_and_no_full_recording(
    db_session, audio_data
):
    chosen = selection(db_session, audio_data)
    content = playback_audio.render_clip(chosen, max_bytes=1_000_000, max_ms=3_000)
    with wave.open(io.BytesIO(content), "rb") as output:
        assert output.getframerate() == 16_000 and output.getnchannels() == 1
        assert (
            output.readframes(output.getnframes())
            == audio_data.pcm[chosen.first_sample * 2 : chosen.last_sample * 2]
        )
    assert chosen.first_sample == 9600 and chosen.last_sample == 22400
    assert len(content) < audio_data.path.stat().st_size


def test_owner_version_and_deletion_fences(db_session, audio_data):
    with pytest.raises(CommandError) as exc:
        selection(db_session, audio_data, user=audio_data.stranger.id)
    assert exc.value.kind == "not_found"
    original = audio_data.asset.checksum_sha256
    audio_data.asset.checksum_sha256 = "f" * 64
    db_session.commit()
    with pytest.raises(CommandError, match="版本已变化"):
        selection(db_session, audio_data)
    audio_data.asset.checksum_sha256 = original
    audio_data.asset.deleted_at = utc_now()
    db_session.commit()
    with pytest.raises(CommandError, match="已不可用"):
        selection(db_session, audio_data)


def test_replaced_local_bytes_fail_hash_even_when_asset_token_did_not_change(
    db_session, audio_data
):
    chosen = selection(db_session, audio_data)
    audio_data.path.write_bytes(b"different source")
    with pytest.raises(CommandError, match="不一致"):
        playback_audio.render_clip(chosen, max_bytes=1_000_000, max_ms=3_000)


def test_missing_word_time_and_reversed_range_are_not_guessed(db_session, audio_data):
    backwards = audio_data.command.model_copy(
        update={"first_word_id": "w000005", "last_word_id": "w000004"}
    )
    with pytest.raises(CommandError, match="连续"):
        selection(db_session, audio_data, backwards)
    missing = audio_data.command.model_copy(update={"last_word_id": "w999999"})
    with pytest.raises(CommandError, match="连续"):
        selection(db_session, audio_data, missing)
    import copy

    evidence = copy.deepcopy(audio_data.tr.evidence_json)
    evidence["words"][3].update(start=None, end=None, alignment_status="missing")
    audio_data.tr.evidence_json = evidence
    db_session.commit()
    with pytest.raises(CommandError, match="缺少"):
        selection(db_session, audio_data)


def test_oversized_clip_rejected_before_media_access(db_session, audio_data):
    chosen = selection(db_session, audio_data)
    with pytest.raises(CommandError, match="30 秒"):
        playback_audio.render_clip(
            replace(chosen, last_sample=chosen.first_sample + 480_001),
            max_bytes=1_000_000,
            max_ms=3_000,
        )


def test_historical_transcript_uses_its_own_source_version(db_session, audio_data):
    from app.interviews.application.transcript_corrections import correct_transcript
    from tests.test_services.interview.test_transcript_corrections import command

    correct_transcript(
        db_session,
        record_id=audio_data.record.id,
        user_pk=audio_data.owner.id,
        command=command(audio_data.tr),
    )
    assert audio_data.record.transcript_id != audio_data.command.transcript_id
    assert (
        selection(db_session, audio_data).transcript_id
        == audio_data.command.transcript_id
    )


def test_media_runs_outside_sessions_and_source_is_rechecked(monkeypatch):
    active = 0
    reads = []
    chosen = SimpleNamespace(storage_uri="opaque-original")
    changed = SimpleNamespace(storage_uri="opaque-replaced")

    @contextmanager
    def factory():
        nonlocal active
        active += 1
        try:
            yield object()
        finally:
            active -= 1

    def select(db, **kwargs):
        assert active == 1
        reads.append(1)
        return chosen if len(reads) == 1 else changed

    def render(*args, **kwargs):
        assert active == 0
        return b"not published"

    monkeypatch.setattr(service, "SessionLocal", factory)
    monkeypatch.setattr(service, "select_playback", select)
    monkeypatch.setattr(service, "render_clip", render)
    with pytest.raises(CommandError, match="期间"):
        service.create_playback(record_id="r", user_pk=1, command=object())
    assert len(reads) == 2 and active == 0


def test_s3_download_is_bounded_and_body_closes_on_hash_mismatch(
    db_session, audio_data, monkeypatch
):
    from app.core.config import settings
    import boto3

    class Body(io.BytesIO):
        def read(self, n=-1):
            assert 0 < n <= 64 * 1024
            return super().read(n)

    body = Body(b"changed")
    seen = []

    @contextmanager
    def client(*args, **kwargs):
        seen.append(kwargs["config"])
        yield SimpleNamespace(
            get_object=lambda **args: {"ContentLength": 7, "Body": body}
        )

    monkeypatch.setattr(boto3, "client", client)
    chosen = replace(
        selection(db_session, audio_data),
        storage_uri=f"s3://{settings.S3_BUCKET_NAME}/owned/audio",
    )
    with pytest.raises(CommandError, match="不一致"):
        playback_audio.render_clip(chosen, max_bytes=1_000_000, max_ms=3_000)
    assert body.closed and seen[0].read_timeout == 10
    assert seen[0].retries["total_max_attempts"] == 1
