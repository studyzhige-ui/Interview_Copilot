"""HTTP response-loss recovery and authorization use the durable application receipt."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.interviews.mock import router
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.interviews.application import mock_flow
from tests.test_services.interview.test_mock_flow_phase5 import _make_run, _stub_turn


@pytest.fixture
def case(db_session):
    owner, other = (
        User(username="alice", hashed_password="x"),
        User(username="bob", hashed_password="x"),
    )
    db_session.add_all([owner, other])
    db_session.flush()
    record, runtime, conversation = _make_run(db_session)
    payload = {
        "request_id": str(uuid4()),
        "answer_text": "源回答",
        "question_message_id": runtime.current_question_message_id,
    }
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client, app, record, runtime, payload, other


def test_post_replay_and_get_receipt_return_the_persisted_reply_without_new_model(
    case, monkeypatch
):
    client, _, record, _, body, _ = case
    _stub_turn(monkeypatch)
    url = f"/api/v1/mock-interviews/{record.id}"
    first = client.post(url + "/answer", json=body)
    assert first.status_code == 200
    monkeypatch.setattr(
        mock_flow.mock_interview_service,
        "generate_next_turn",
        lambda **_: pytest.fail("second model call"),
    )
    second = client.post(url + "/answer", json=body)
    receipt = client.get(url + "/answer-receipts/" + body["request_id"])
    assert second.status_code == receipt.status_code == 200
    assert second.json() == receipt.json()["response"] == first.json()
    assert receipt.json()["status"] == "completed"


def test_receipt_and_replay_cannot_cross_ownership(case, monkeypatch):
    client, app, record, _, body, other = case
    _stub_turn(monkeypatch)
    url = f"/api/v1/mock-interviews/{record.id}"
    assert client.post(url + "/answer", json=body).status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.get(url + "/answer-receipts/" + body["request_id"]).status_code == 404
    assert client.post(url + "/answer", json=body).status_code == 404


def test_missing_receipt_and_invalid_or_conflicting_intent_do_not_generate(
    case, monkeypatch
):
    client, _, record, _, body, _ = case
    _stub_turn(monkeypatch)
    url = f"/api/v1/mock-interviews/{record.id}"
    assert client.get(url + "/answer-receipts/" + body["request_id"]).status_code == 404
    assert (
        client.post(
            url + "/answer", json={k: v for k, v in body.items() if k != "request_id"}
        ).status_code
        == 422
    )
    assert client.post(url + "/answer", json=body).status_code == 200
    monkeypatch.setattr(
        mock_flow.mock_interview_service,
        "generate_next_turn",
        lambda **_: pytest.fail("second model call"),
    )
    assert (
        client.post(url + "/answer", json={**body, "answer_text": "篡改"}).status_code
        == 409
    )
