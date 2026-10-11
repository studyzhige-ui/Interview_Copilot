"""Account-scoped memory consent is versioned, never an implicit opt-in."""

import pytest
from app.memory import lifecycle
from app.schemas.agent_memory import AgentMemorySettingsUpdate


def test_contribution_requires_explicit_owner_version_and_can_be_revoked(db, owners):
    owner, other = owners
    initial = lifecycle.get_settings(db, user_pk=owner.id)
    assert initial.contribution_enabled is False
    updated = lifecycle.update_settings(
        db,
        user_pk=owner.id,
        command=AgentMemorySettingsUpdate(
            expected_version=initial.version,
            recall_enabled=True,
            contribution_enabled=True,
        ),
    )
    assert updated.contribution_enabled and updated.version > initial.version
    assert lifecycle.get_settings(db, user_pk=other.id).contribution_enabled is False
    with pytest.raises(lifecycle.AgentMemoryConflictError):
        lifecycle.update_settings(
            db,
            user_pk=owner.id,
            command=AgentMemorySettingsUpdate(
                expected_version=initial.version,
                recall_enabled=False,
                contribution_enabled=False,
            ),
        )
    revoked = lifecycle.update_settings(
        db,
        user_pk=owner.id,
        command=AgentMemorySettingsUpdate(
            expected_version=updated.version,
            recall_enabled=False,
            contribution_enabled=False,
        ),
    )
    assert not revoked.contribution_enabled and not revoked.recall_enabled
