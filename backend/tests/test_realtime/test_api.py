from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.api.interviews import realtime
from app.core.security import get_current_user
from app.db.database import get_db
from app.core.config import settings
from app.interviews.application.live_media_turns import MediaLease


@pytest.fixture
def client(monkeypatch):
    db = SimpleNamespace(closed=False)
    db.close = lambda: setattr(db, "closed", True)
    actor = SimpleNamespace(id=7, username="owned")
    app = FastAPI()
    app.include_router(realtime.router)
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: db
    find_spec = realtime.importlib.util.find_spec
    monkeypatch.setattr(
        realtime.importlib.util,
        "find_spec",
        lambda name: object() if name == "aiortc" else find_spec(name),
    )
    monkeypatch.setattr(settings, "REALTIME_ENABLED", True)
    monkeypatch.setattr(settings, "TRANSCRIPTION_PROVIDER", "local_qwen_asr")
    monkeypatch.setattr(settings, "TTS_PROVIDER", "local_qwen3_tts")
    with TestClient(app) as c:
        yield c, db


def test_disabled_and_unapproved_signalling_fail_before_session_claim(
    client, monkeypatch
):
    c, _ = client
    monkeypatch.setattr(
        realtime.application, "claim", lambda *a: pytest.fail("must not claim")
    )
    body = {"client_session_id": str(uuid4()), "sdp": "invalid"}
    assert c.post("/mock-interviews/r/media/offer", json=body).status_code == 422
    monkeypatch.setattr(settings, "REALTIME_ENABLED", False)
    assert c.post("/mock-interviews/r/media/offer", json=body).status_code == 409


def test_offer_releases_auth_transaction_and_uses_server_owner(client, monkeypatch):
    c, db = client
    monkeypatch.setattr(realtime.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(realtime.transport, "validate_offer", lambda *a: None)
    sid = str(uuid4())
    calls = []

    def claim(record, owner, username, client_id):
        assert db.closed
        calls.append((record, owner, username, client_id))
        return MediaLease(sid, 1, record, owner, username)

    class Peer:
        def __init__(self, lease, *a, **k):
            self.lease = lease

        async def negotiate(self, sdp):
            assert db.closed
            return "validated-answer"

    monkeypatch.setattr(realtime.application, "claim", claim)
    monkeypatch.setattr(realtime.application, "InterviewMedia", lambda _: object())
    monkeypatch.setattr(realtime.transport, "Peer", Peer)
    monkeypatch.setattr(realtime.transport, "PEERS", {})
    cid = str(uuid4())
    response = c.post(
        "/mock-interviews/r/media/offer", json={"client_session_id": cid, "sdp": "test"}
    )
    assert response.status_code == 200, response.text
    assert calls == [("r", 7, "owned", cid)]
    assert (
        response.json()["session_id"] == sid
        and response.headers["cache-control"] == "no-store"
    )
    assert realtime.transport._creating == 0


def test_media_cannot_extend_its_own_authority_without_http_authentication():
    app = FastAPI()
    app.include_router(realtime.router)
    with TestClient(app) as c:
        response = c.post(
            f"/mock-interviews/r/media/{uuid4()}/heartbeat", json={"generation": 1}
        )
    assert response.status_code == 401
