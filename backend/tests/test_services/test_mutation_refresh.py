"""Cached ORM instances cannot bypass current mutation/erasure fences.

Core updates deliberately leave a loaded identity stale. This isolates refresh
semantics; real PostgreSQL lock/transaction campaigns remain separate gates.
"""

from datetime import timedelta

import pytest

from app.db.types import utc_now
from app.models.user import User
from app.models.chat import Conversation
from app.models.interview_record import InterviewRecord
from app.models.copilot_preference import CopilotPreference
from app.models.long_term_memory import AgentMemorySetting, LongTermAgentMemory
from app.models.memory_pipeline import MemoryWorkspace
from app.models.artifact import ArtifactVersion
from app.schemas.personalization import CopilotPreferenceUpdate, ScopedGuidanceUpdate
from app.schemas.agent_memory import AgentMemorySettingsUpdate, AgentMemoryUpdate
from app.schemas.artifact import ArtifactWriteInput
from app.career.application import personalization, artifacts, process, offers
from app.memory import lifecycle, projections


def storage_change(db, row, **values):
    table = row.__table__
    statement = table.update()
    for column in table.primary_key:
        statement = statement.where(column == getattr(row, column.name))
    db.connection().execute(statement.values(**values))


@pytest.fixture
def owner(db_session):
    row = User(username="mutation-refresh", hashed_password="x")
    db_session.add(row)
    db_session.flush()
    return row


def test_stale_global_preference_cannot_overwrite_current_version(db_session, owner):
    row = CopilotPreference(user_id=owner.id, instructions_json=["old"], version=1)
    db_session.add(row)
    db_session.flush()
    storage_change(db_session, row, version=2, instructions_json=["current"])
    assert row.version == 1
    with pytest.raises(personalization.PersonalizationConflictError):
        personalization.replace_copilot_preference(
            db_session,
            user_pk=owner.id,
            command=CopilotPreferenceUpdate(
                expected_version=1, instructions=["stale replacement"]
            ),
        )
    db_session.refresh(row)
    assert row.instructions_json == ["current"] and row.version == 2


def test_stale_scoped_guidance_cannot_clear_newer_user_choices(db_session, owner):
    conversation = Conversation(user_id=owner.id)
    record = InterviewRecord(user_id=owner.id, source="upload")
    db_session.add_all([conversation, record])
    db_session.flush()
    for row, field, operation, kwargs in (
        (
            conversation,
            "guidance_version",
            personalization.update_conversation_guidance,
            {"conversation_id": conversation.id},
        ),
        (
            record,
            "debrief_guidance_version",
            personalization.update_debrief_guidance,
            {"interview_record_id": record.id},
        ),
    ):
        storage_change(db_session, row, **{field: 1})
        assert getattr(row, field) == 0
        with pytest.raises(personalization.PersonalizationConflictError):
            operation(
                db_session,
                user_pk=owner.id,
                command=ScopedGuidanceUpdate(expected_version=0, guidance=None),
                **kwargs,
            )
        assert getattr(row, field) == 1


def test_stale_memory_settings_cannot_reenable_disabled_contribution(db_session, owner):
    row = AgentMemorySetting(user_id=owner.id, contribution_enabled=True, version=1)
    db_session.add(row)
    db_session.flush()
    storage_change(db_session, row, version=2, contribution_enabled=False)
    with pytest.raises(lifecycle.AgentMemoryConflictError):
        lifecycle.update_settings(
            db_session,
            user_pk=owner.id,
            command=AgentMemorySettingsUpdate(
                expected_version=1, recall_enabled=True, contribution_enabled=True
            ),
        )
    db_session.refresh(row)
    assert row.contribution_enabled is False and row.version == 2


def test_deleted_memory_cannot_be_revived_from_a_stale_identity(db_session, owner):
    row = LongTermAgentMemory(
        user_id=owner.id,
        semantic_key="comparison",
        content="Use comparisons",
        applicability="Comparing approaches",
        valence="effective",
        confidence=0.8,
        content_hash="0" * 64,
    )
    db_session.add(row)
    db_session.flush()
    storage_change(
        db_session,
        row,
        status="deleted",
        version=2,
        content="",
        applicability="",
        index_text="",
    )
    with pytest.raises(lifecycle.AgentMemoryConflictError):
        lifecycle.update_memory(
            db_session,
            user_pk=owner.id,
            memory_id=row.id,
            command=AgentMemoryUpdate(
                expected_version=1, content="restore old data", applicability="always"
            ),
        )
    db_session.refresh(row)
    assert row.status == "deleted" and row.content == "" and row.version == 2


def test_workspace_invalidation_clears_a_new_lease_not_only_the_cached_empty_one(
    db_session, owner
):
    row = MemoryWorkspace(user_id=owner.id)
    db_session.add(row)
    db_session.flush()
    storage_change(
        db_session,
        row,
        lease_token="new-lease",
        lease_until=utc_now() + timedelta(minutes=5),
        input_hash="x" * 64,
        index_json=[{"new": "private"}],
        revision=9,
    )
    assert row.lease_token is None
    projections.invalidate_workspace(db_session, owner.id)
    db_session.flush()
    db_session.refresh(row)
    assert row.lease_token is None and row.lease_until is None
    assert row.index_json == [] and row.input_hash == "" and row.revision == 9


def test_archived_artifact_rejects_a_stale_edit_without_new_version(db_session, owner):
    row = artifacts.save_artifact_explicitly(
        db_session,
        user_pk=owner.id,
        operation_key="initial",
        artifact_kind="report",
        version=ArtifactWriteInput(title="Report", content_text="Original"),
    )
    storage_change(db_session, row, archived_at=utc_now())
    with pytest.raises(artifacts.ArtifactArchivedError):
        artifacts.edit_artifact(
            db_session,
            user_pk=owner.id,
            artifact_id=row.id,
            operation_key="stale-edit",
            version=ArtifactWriteInput(title="Report", content_text="Replacement"),
        )
    assert db_session.query(ArtifactVersion).filter_by(artifact_id=row.id).count() == 1


def test_closed_opportunity_cannot_take_new_events_from_cached_active_state(db_session):
    from tests.test_services.test_career_process_service import _user, _create, _append

    user = _user(db_session)
    row = _create(db_session, user).opportunity
    storage_change(db_session, row, outcome="rejected")
    with pytest.raises(process.OpportunityArchivedError):
        _append(db_session, user, row.id, "hiring_step", step_summary="New interview")


def test_changed_offer_requires_new_confirmation_not_a_cached_token(db_session):
    from tests.test_services.test_offer_service import (
        _user,
        _job_id,
        _terms,
        _source,
        _job_owner,
        _source_checker,
    )

    user = _user(db_session, "refresh-offer")
    row = offers.record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=_job_id(user),
        operation_key="first",
        terms=_terms(),
        source=_source(user),
        job_owner_checker=_job_owner,
        source_checker=_source_checker,
    )
    token = offers.current_offer_token(row)
    storage_change(
        db_session, row, terms_json={**row.terms_json, "base_salary_amount": "120000"}
    )
    with pytest.raises(offers.OfferStaleConfirmationError):
        offers.confirm_offer_terms_change(
            db_session,
            user_pk=user.id,
            offer_id=row.id,
            job_opportunity_id=_job_id(user),
            operation_key="stale-confirmation",
            expected_current_token=token,
            resolution="replace",
            terms=_terms("110000"),
            candidate_source=_source(user, suffix="new"),
            confirmation_source=_source(user, "user_assertion", "confirm"),
            job_owner_checker=_job_owner,
            source_checker=_source_checker,
        )
