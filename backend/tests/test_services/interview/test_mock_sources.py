import hashlib
import pytest
from pydantic import ValidationError
from app.db.types import utc_now
from app.models.user import User
from app.models.job_opportunity import JobOpportunity
from app.models.job_description_snapshot import JobDescriptionSnapshot
from app.schemas.chat import MockStartRequest
from app.agent_runtime.tools.mock_interview import StartMockInterviewArgs
from app.interviews.application.mock_sources import resolve_job_description
from app.interviews.application.mock_sources import MockJobDescriptionUnavailable


@pytest.mark.parametrize("model", [MockStartRequest, StartMockInterviewArgs])
def test_ui_agent_share_exact_input_contract(model):
    assert model(resume_id="resume", jd_text="x" * 4500).input_mode == "text"
    for extra in (
        {},
        {"jd_text": "x" * 19},
        {"jd_text": "x" * 50001},
        {"jd_snapshot_id": "jds", "jd_snapshot_version": 1},
        {
            "jd_text": "x" * 50,
            "jd_snapshot_id": "jds",
            "jd_snapshot_version": 1,
            "job_opportunity_id": "job",
        },
    ):
        with pytest.raises(ValidationError):
            model(resume_id="resume", **extra)
    accepted = model(
        resume_id="resume",
        jd_snapshot_id="jds",
        jd_snapshot_version=1,
        job_opportunity_id="job",
    )
    assert accepted.jd_text is None


def test_snapshot_resolution_is_owned_versioned_and_never_silently_truncated(
    db_session,
):
    owner = User(username="jd-owner", hashed_password="x")
    stranger = User(username="jd-stranger", hashed_password="x")
    db_session.add_all([owner, stranger])
    db_session.flush()
    opportunity = JobOpportunity(
        user_id=owner.id,
        company_name="Example",
        job_title="Engineer",
        idempotency_key="jd-contract",
    )
    db_session.add(opportunity)
    db_session.flush()
    text = "An exact, immutable engineering job description."
    snapshot = JobDescriptionSnapshot(
        job_opportunity_id=opportunity.id,
        version=1,
        original_url="https://example.com/job",
        normalized_url="https://example.com/job",
        observed_at=utc_now(),
        provider="user",
        canonical_content=text,
        content_checksum=hashlib.sha256(text.encode()).hexdigest(),
        source_kind="typed_product_ui",
        source_identity="ui",
        source_version="1",
        idempotency_key="source",
        creation_fingerprint="a" * 64,
    )
    db_session.add(snapshot)
    db_session.flush()
    args = dict(
        jd_text=None,
        job_opportunity_id=opportunity.id,
        jd_snapshot_id=snapshot.id,
        jd_snapshot_version=1,
    )
    assert resolve_job_description(db_session, user_pk=owner.id, **args) == text
    with pytest.raises(MockJobDescriptionUnavailable):
        resolve_job_description(db_session, user_pk=stranger.id, **args)
    with pytest.raises(MockJobDescriptionUnavailable):
        resolve_job_description(
            db_session, user_pk=owner.id, **{**args, "jd_snapshot_version": 2}
        )
    with pytest.raises(MockJobDescriptionUnavailable):
        resolve_job_description(db_session, user_pk=owner.id, jd_text="x" * 50001)
