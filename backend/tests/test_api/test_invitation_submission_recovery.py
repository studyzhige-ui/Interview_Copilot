"""Receipt recovery is owner-scoped and read-only; cancellation fences late POST."""

from app.career.application import invitation_submission_service as service
from app.models.application_operation import ApplicationOperation
from app.models.interview_record import InterviewRecord
from app.models.invitation_submission import InvitationSubmission
from app.models.job_opportunity import JobOpportunity
from app.schemas.interview_invitation import ConfirmInterviewInvitation
from tests.test_api.test_interview_invitations_api import invitation_api, _payload  # noqa: F401

PREFIX = "/api/v1/career/interview-invitations"


def test_registered_command_can_resume_after_the_request_handler_dies(
    invitation_api,  # noqa: F811 -- imported pytest fixture
    db_session,
):  # noqa: F811
    client, _, owner, _ = invitation_api
    command = ConfirmInterviewInvitation.model_validate(_payload("registered-only"))
    service.register_submission(db_session, user_pk=owner.id, command=command)
    assert db_session.query(InterviewRecord).count() == 0
    read = client.get(
        f"{PREFIX}/submissions/receipt",
        params={"idempotency_key": command.idempotency_key},
    )
    assert read.status_code == 200
    assert read.json()["status"] == "pending"
    assert read.json()["command"]["facts"]["company_name"] == command.facts.company_name
    assert db_session.query(ApplicationOperation).count() == 0
    resumed = client.post(
        f"{PREFIX}/submissions/resume",
        json={"idempotency_key": command.idempotency_key},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["verification"]["conclusion"] == "verified"
    read = client.get(
        f"{PREFIX}/submissions/receipt",
        params={"idempotency_key": command.idempotency_key},
    ).json()
    assert read["status"] == "committed"
    assert read["result"]["operation_id"] == resumed.json()["operation_id"]
    assert read["command"] is None
    replay = client.post(
        f"{PREFIX}/submissions/resume",
        json={"idempotency_key": command.idempotency_key},
    )
    assert replay.json()["replayed"] is True
    assert db_session.query(InterviewRecord).count() == 1
    assert db_session.query(JobOpportunity).count() == 1


def test_cancel_not_received_fences_delayed_original_post(invitation_api, db_session):  # noqa: F811
    client, *_ = invitation_api
    key = "delayed-before-server"
    assert (
        client.get(
            f"{PREFIX}/submissions/receipt", params={"idempotency_key": key}
        ).json()["status"]
        == "not_received"
    )
    cancelled = client.post(
        f"{PREFIX}/submissions/cancel", json={"idempotency_key": key}
    )
    assert cancelled.json()["status"] == "cancelled"
    late = client.post(f"{PREFIX}/confirm", json=_payload(key))
    assert late.status_code == 409
    assert db_session.query(InterviewRecord).count() == 0
    assert db_session.query(ApplicationOperation).count() == 0
    assert db_session.query(InvitationSubmission).one().request_json is None


def test_cancel_after_commit_returns_receipt_and_never_undoes_business(
    invitation_api,  # noqa: F811 -- imported pytest fixture
    db_session,
):  # noqa: F811
    client, *_ = invitation_api
    key = "committed-lost-response"
    original = client.post(f"{PREFIX}/confirm", json=_payload(key)).json()
    cancelled = client.post(
        f"{PREFIX}/submissions/cancel", json={"idempotency_key": key}
    ).json()
    assert cancelled["status"] == "committed"
    assert cancelled["result"]["operation_id"] == original["operation_id"]
    assert db_session.query(InterviewRecord).count() == 1


def test_receipt_does_not_reveal_other_users_command_or_result(
    invitation_api,  # noqa: F811 -- imported pytest fixture
    db_session,
):  # noqa: F811
    client, principal, owner, other = invitation_api
    key = "same-key-two-owners"
    service.register_submission(
        db_session,
        user_pk=owner.id,
        command=ConfirmInterviewInvitation.model_validate(_payload(key)),
    )
    principal["user"] = other
    hidden = client.get(
        f"{PREFIX}/submissions/receipt", params={"idempotency_key": key}
    ).json()
    assert hidden == {
        "status": "not_received",
        "idempotency_key": key,
        "result": None,
        "command": None,
    }
    assert (
        client.post(
            f"{PREFIX}/submissions/resume", json={"idempotency_key": key}
        ).status_code
        == 404
    )
    client.post(f"{PREFIX}/submissions/cancel", json={"idempotency_key": key})
    principal["user"] = owner
    assert (
        client.post(
            f"{PREFIX}/submissions/resume", json={"idempotency_key": key}
        ).status_code
        == 200
    )


def test_conflicting_replay_never_rejects_the_original_pending_command(
    invitation_api,  # noqa: F811 -- imported pytest fixture
    db_session,
):  # noqa: F811
    client, _, owner, _ = invitation_api
    key = "immutable-command"
    service.register_submission(
        db_session,
        user_pk=owner.id,
        command=ConfirmInterviewInvitation.model_validate(_payload(key)),
    )
    changed = _payload(key)
    changed["facts"]["company_name"] = "tampered"
    assert client.post(f"{PREFIX}/confirm", json=changed).status_code == 409
    receipt = client.get(
        f"{PREFIX}/submissions/receipt", params={"idempotency_key": key}
    ).json()
    assert receipt["status"] == "pending"
    assert receipt["command"]["facts"]["company_name"] == "Example Corp"


def test_lost_verification_is_not_reported_as_success(invitation_api, db_session):  # noqa: F811
    client, *_ = invitation_api
    key = "bad-receipt"
    result = client.post(f"{PREFIX}/confirm", json=_payload(key)).json()
    op = db_session.get(ApplicationOperation, result["operation_id"])
    op.status = "unknown"
    db_session.commit()
    assert (
        client.get(
            f"{PREFIX}/submissions/receipt", params={"idempotency_key": key}
        ).status_code
        == 500
    )
