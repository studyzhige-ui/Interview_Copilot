import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client():
    from app.api import chat as chat_api
    from app.db.database import get_db
    from app.core.security import get_current_user

    class FakeUser:
        username = "alice"

    async def fake_user():
        return FakeUser()

    app = FastAPI()
    app.include_router(chat_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app), chat_api, get_db


def test_transcript_endpoint_returns_structured_state(monkeypatch):
    client, chat_api, get_db = _build_client()

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return type("Session", (), {"id": "s1", "user_id": "alice"})()

    class FakeDB:
        def query(self, model):
            return FakeQuery()

    monkeypatch.setattr(
        chat_api,
        "transcript_service",
        type(
            "TranscriptSvc",
            (),
            {
                "get_session_meta": staticmethod(
                    lambda session_id: {
                        "turn_count": 2,
                        "compaction_cursor": 4,
                        "memory_cursor": 4,
                        "working_state": json.dumps({"goal": "redis", "summary": "focus on redis"}),
                    }
                ),
                "get_full_transcript": staticmethod(
                    lambda session_id: [
                        {"seq": 1, "role": "User", "content": "hello", "created_at": "2024-01-01T00:00:00"}
                    ]
                ),
            },
        )(),
    )
    monkeypatch.setattr(
        chat_api,
        "interview_state_service",
        type("InterviewSvc", (), {"get_state": staticmethod(lambda session_id, user_id: {"phase": "probing"})})(),
    )

    client.app.dependency_overrides[get_db] = lambda: FakeDB()

    response = client.get("/api/v1/chat/transcript", params={"session_id": "s1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["working_state"]["goal"] == "redis"
    assert payload["interview_state"]["phase"] == "probing"
    assert payload["memory_cursor"] == 4
