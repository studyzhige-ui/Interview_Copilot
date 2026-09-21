"""Authenticated transcript HTTP contracts and real local clip bytes (no models)."""

from contextlib import contextmanager
import io
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.interviews.transcripts import router
from app.core.security import get_current_user
from app.db.database import get_db
from app.interviews.application import transcript_playback
from tests.test_services.interview import test_transcript_playback as playback_cases

# Reuse the real source-audio fixture in the HTTP boundary campaign.
audio_data = playback_cases.audio_data


@pytest.fixture
def client(db_session, audio_data, monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: audio_data.owner
    app.dependency_overrides[get_db] = lambda: db_session

    # The real application owns separate sessions. The SQLite regression shares
    # its rollback fixture; session-lifetime separation has a dedicated test.
    @contextmanager
    def factory():
        yield db_session

    monkeypatch.setattr(transcript_playback, "SessionLocal", factory)
    with TestClient(app) as connection:
        yield connection, app


def test_page_exposes_exact_source_identity_and_clip_uses_that_transcript(
    client, audio_data
):
    connection, _ = client
    root = f"/api/v1/interview-records/{audio_data.record.id}/transcript"
    page = connection.get(root)
    assert page.status_code == 200
    view = page.json()
    assert view["audio_sha256"] == audio_data.asset.checksum_sha256
    assert view["audio_file_asset_version"] == f"sha256:{view['audio_sha256']}"
    clip = connection.post(f"{root}/playback", json=audio_data.command.model_dump())
    assert clip.status_code == 200
    assert clip.headers["x-transcript-id"] == view["transcript_id"]
    assert clip.headers["x-audio-source-sha256"] == view["audio_sha256"]
    assert clip.headers["cache-control"] == "private, no-store"
    with wave.open(io.BytesIO(clip.content), "rb") as source:
        assert source.readframes(source.getnframes()) == audio_data.pcm[19200:44800]
    assert audio_data.asset.storage_uri not in repr(dict(clip.headers))


def test_cross_owner_cannot_read_or_play_transcript(client, audio_data):
    connection, app = client
    app.dependency_overrides[get_current_user] = lambda: audio_data.stranger
    root = f"/api/v1/interview-records/{audio_data.record.id}/transcript"
    assert connection.get(root).status_code == 404
    assert (
        connection.post(
            f"{root}/playback", json=audio_data.command.model_dump()
        ).status_code
        == 404
    )


def test_correction_http_returns_stable_receipt_and_old_version_is_immutable(
    client, audio_data
):
    from tests.test_services.interview.test_transcript_corrections import command

    connection, _ = client
    root = f"/api/v1/interview-records/{audio_data.record.id}/transcript"
    payload = command(audio_data.tr).model_dump(exclude_unset=True)
    response = connection.post(f"{root}/corrections", json=payload)
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["reanalysis_required"] is True
    assert (
        connection.get(f"{root}/corrections/{payload['request_id']}").json() == receipt
    )
    assert connection.post(f"{root}/corrections", json=payload).json() == receipt
    old = connection.get(root, params={"transcript_id": audio_data.tr.id}).json()
    assert old["words"][3]["text"] == "负责"
    assert old["current_transcript_id"] != old["transcript_id"]
    assert (
        connection.get(f"{root}/corrections").json()["items"][0]["transcript_id"]
        == receipt["transcript_id"]
    )


def test_playback_shape_rejects_paths_urls_and_unbounded_requests(client, audio_data):
    connection, _ = client
    url = f"/api/v1/interview-records/{audio_data.record.id}/transcript/playback"
    payload = audio_data.command.model_dump()
    for field, value in (
        ("url", "https://not-accepted"),
        ("path", "/etc/passwd"),
        ("first_word_id", "w123456789"),
    ):
        assert connection.post(url, json={**payload, field: value}).status_code == 422


def test_authentication_read_transaction_is_closed_before_media_admission(
    client, audio_data, db_session, monkeypatch
):
    from types import SimpleNamespace
    from app.media.application import workers

    connection, _ = client
    record_id = audio_data.record.id
    tr_id = audio_data.tr.id
    sha = audio_data.asset.checksum_sha256
    owner_id = audio_data.owner.id
    payload = audio_data.command.model_dump()
    observed = []

    class Probe:
        async def run(self, fn, **kwargs):
            assert not db_session.in_transaction()
            assert kwargs["user_pk"] == owner_id
            observed.append(kwargs)
            return SimpleNamespace(transcript_id=tr_id, sha256=sha), b"verified"

    monkeypatch.setattr(workers, "pool", lambda _: Probe())
    response = connection.post(
        f"/api/v1/interview-records/{record_id}/transcript/playback", json=payload
    )
    assert response.status_code == 200 and len(observed) == 1
