from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.types import utc_now
from app.models.user import User
from app.models.interview_record import InterviewRecord
from app.models.mock_media import MockMediaLease
from app.interviews.application.live_media import claim, MediaConflict
from app.api.interviews import realtime
from app.core.security import get_current_user


def test_media_lease_is_owned_and_new_epoch_fences_old_connection(db_session):
    db = db_session
    user = User(username="live-owner", hashed_password="test")
    db.add(user)
    db.flush()
    record = InterviewRecord(
        user_id=user.id, source="mock", status="mock_in_progress", title="Live"
    )
    db.add(record)
    db.flush()
    claim(
        db,
        record_id=record.id,
        username=user.username,
        client_session_id="c1",
        connection_id="one",
    )
    lease = db.get(MockMediaLease, record.id)
    assert lease.connection_id == "one"
    with pytest.raises(MediaConflict):
        claim(
            db,
            record_id=record.id,
            username=user.username,
            client_session_id="c2",
            connection_id="two",
        )
    claim(
        db,
        record_id=record.id,
        username=user.username,
        client_session_id="c1",
        connection_id="new",
    )
    assert db.get(MockMediaLease, record.id).connection_id == "new"
    lease.expires_at = utc_now() - timedelta(seconds=1)
    db.flush()
    claim(
        db,
        record_id=record.id,
        username=user.username,
        client_session_id="c2",
        connection_id="two",
    )
    assert db.get(MockMediaLease, record.id).client_session_id == "c2"
    record.status = "completed"
    db.flush()
    with pytest.raises(MediaConflict):
        claim(
            db,
            record_id=record.id,
            username=user.username,
            client_session_id="c2",
            connection_id="three",
        )


def test_feature_is_explicit_and_http_never_allocates_when_disabled(monkeypatch):
    app = FastAPI()
    app.include_router(realtime.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="a"
    )
    monkeypatch.setattr(realtime.config, "enabled", False)
    allocate = AsyncMock()
    monkeypatch.setattr(realtime.registry, "connect", allocate)
    with TestClient(app) as client:
        assert (
            client.get("/mock-interviews/media-capabilities").json()["enabled"] is False
        )
        response = client.post(
            "/mock-interviews/r/media/offer",
            headers={"Authorization": "Bearer test"},
            json={
                "client_session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "sdp": "sdp",
            },
        )
    assert response.status_code == 503
    allocate.assert_not_called()


def test_playback_reports_are_owner_scoped_and_keep_distinct_counts(db_session):
    from app.models.mock_media import MockMediaPlayback
    from app.interviews.application.live_media import playback_reports
    from app.models.chat import Conversation, ConversationMessage

    db = db_session
    owner = User(username="report-owner", hashed_password="test")
    stranger = User(username="report-stranger", hashed_password="test")
    db.add_all([owner, stranger])
    db.flush()
    record = InterviewRecord(
        user_id=owner.id, source="mock", status="mock_in_progress", title="Live"
    )
    db.add(record)
    db.flush()
    conversation = Conversation(
        user_id=owner.id, subject_type="interview_record", subject_id=record.id
    )
    db.add(conversation)
    db.flush()
    message = ConversationMessage(
        conversation_id=conversation.id, seq=1, role="assistant", content="Question"
    )
    db.add(message)
    db.flush()
    report = MockMediaPlayback(
        record_id=record.id,
        playback_id="report",
        message_id=message.id,
        generated_samples=24000,
        delivered_samples=12000,
        client_reported_samples=6000,
        sample_rate=24000,
        status="interrupted",
    )
    db.add(report)
    db.flush()
    with pytest.raises(MediaConflict):
        playback_reports(db, record_id=record.id, username=stranger.username)
    result = playback_reports(db, record_id=record.id, username=owner.username)
    assert len(result) == 1
    assert (
        result[0].generated_samples,
        result[0].delivered_samples,
        result[0].client_reported_samples,
    ) == (24000, 12000, 6000)
