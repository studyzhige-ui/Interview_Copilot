from dataclasses import replace
from uuid import uuid4
import pytest
from tests.conftest import NoCloseSession
from tests.test_services.interview.test_mock_flow_phase5 import _make_run, _stub_turn
from app.models.user import User
from app.models.mock_media_session import MockMediaSession, MockMediaPlayback
from app.models.mock_answer_submission import MockAnswerSubmission
from app.interviews.application import live_media_turns as service


@pytest.fixture
def case(db_session, monkeypatch):
    owner = User(username="alice", hashed_password="x")
    db_session.add(owner)
    db_session.flush()
    record, cursor, conversation = _make_run(db_session)
    monkeypatch.setattr(service, "SessionLocal", lambda: NoCloseSession(db_session))
    lease = service.claim(record.id, owner.id, owner.username, str(uuid4()))
    return lease, record, cursor, db_session


def test_reconnect_retains_identity_increments_generation_and_fences_old_close(case):
    lease, record, _, db = case
    row = db.get(MockMediaSession, lease.id)
    new = service.claim(record.id, lease.user_pk, lease.username, row.client_session_id)
    assert new.id == lease.id and new.generation == lease.generation + 1
    with pytest.raises(ValueError):
        service.renew(lease)
    service.release(lease)
    service.renew(new)
    with pytest.raises(ValueError):
        service.claim(record.id, lease.user_pk, lease.username, str(uuid4()))
    with pytest.raises(ValueError):
        service.state(replace(new, user_pk=99999))


def test_playback_counter_is_monotonic_scoped_and_never_a_hearing_fact(case):
    lease, _, cursor, db = case
    audio_id = service.register_audio(
        lease, cursor.current_question_message_id, "hello", b"\0\0" * 240, 24000
    )
    service.acknowledge(lease, audio_id, 100, False)
    for samples, complete in ((99, False), (241, False), (101, True), (True, False)):
        with pytest.raises(ValueError):
            service.acknowledge(lease, audio_id, samples, complete)
    service.acknowledge(lease, audio_id, 240, True)
    row = db.get(MockMediaPlayback, audio_id)
    db.refresh(row)
    assert (
        row.state == "client_reported"
        and row.reported_samples == row.generated_samples == 240
    )
    assert not hasattr(row, "heard")
    with pytest.raises(ValueError):
        service.acknowledge(replace(lease, generation=99), audio_id, 240, True)


async def test_final_answer_uses_existing_transaction_and_receipt(case, monkeypatch):
    lease, _, cursor, db = case
    _stub_turn(monkeypatch)
    request = str(uuid4())
    question_id = cursor.current_question_message_id
    result = await service.submit_final(lease, question_id, "实时最终回答", request)
    receipt = db.get(MockAnswerSubmission, (lease.record_id, request))
    assert (
        receipt.status == "completed"
        and receipt.response_json["message"] == result["message"]
    )
    assert db.get(MockMediaSession, lease.id).pending_request_id == request
    # Reconnect sync is read-only, even after a completed receipt exists.
    snapshot = service.state(lease)
    assert snapshot["request_status"] == "completed" and not snapshot["answer_pending"]
    replay = await service.submit_final(lease, question_id, "实时最终回答", request)
    assert result == replay


async def test_revoked_media_generation_cannot_save_an_answer(case, monkeypatch):
    lease, _, cursor, db = case
    service.release(lease)
    with pytest.raises(ValueError):
        await service.submit_final(
            lease, cursor.current_question_message_id, "do not persist", str(uuid4())
        )
    assert db.query(MockAnswerSubmission).count() == 0
