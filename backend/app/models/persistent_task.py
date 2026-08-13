"""Persistent automation definition and its separate trigger ingress.

``PersistentTaskTrigger`` is not a Run object.  A trigger remains an intake
record until Conversation admission binds it to the authoritative
``ConversationTurn`` identity.  Multiple records may bind to the same Turn,
which is the durable representation of trigger merging.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


PERSISTENT_TASK_STATES = ("active", "paused")
PERSISTENT_TASK_TRIGGER_KINDS = ("scheduled", "event")
AUTOMATION_TRIGGER_KINDS = ("scheduled", "event", "manual")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class PersistentTask(Base):
    """One user-confirmed current automation definition."""

    __tablename__ = "persistent_tasks"
    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'paused')",
            name="ck_persistent_tasks_state",
        ),
        CheckConstraint(
            "trigger_kind IN ('scheduled', 'event')",
            name="ck_persistent_tasks_trigger_kind",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_persistent_tasks_user_idempotency",
        ),
        UniqueConstraint(
            "conversation_id",
            name="uq_persistent_tasks_conversation",
        ),
        Index(
            "ix_persistent_tasks_user_state_updated",
            "user_id",
            "state",
            "updated_at",
        ),
        Index(
            "ix_persistent_tasks_schedule_due",
            "state",
            "trigger_kind",
            "next_due_at",
        ),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("pt"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    title = Column(String(120), nullable=False)
    instruction = Column(Text, nullable=False)
    state = Column(String(16), nullable=False, default="active")
    version = Column(Integer, nullable=False, default=1)

    trigger_kind = Column(String(16), nullable=False)
    trigger_spec_json = Column(JSON, nullable=False)
    read_scope_json = Column(JSON, nullable=False, default=list)
    action_scope_json = Column(JSON, nullable=False, default=list)
    # Concrete Tool names only.  Runtime admission revalidates them against an
    # injected set of cloud-sustainable real definitions on every run.
    allowed_tool_names_json = Column(JSON, nullable=False, default=list)

    user_request_identity = Column(String(256), nullable=False)
    user_request_version = Column(String(128), nullable=True)
    idempotency_key = Column(String(200), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)

    # When the user stops the current automation Turn, already-merged triggers
    # stay retained but cannot immediately compensate.  A later normal/manual
    # occurrence releases this gate.  This is intake control, not task state.
    compensation_blocked_at = Column(DateTime, nullable=True)
    # Authoritative UTC scheduler cursor. Event definitions leave it NULL.
    next_due_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class PersistentTaskTrigger(Base):
    """One idempotent scheduled/event/manual automation occurrence."""

    __tablename__ = "persistent_task_triggers"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('scheduled', 'event', 'manual')",
            name="ck_persistent_task_triggers_kind",
        ),
        CheckConstraint(
            "admitted_at IS NOT NULL OR admitted_turn_id IS NULL",
            name="ck_persistent_task_triggers_admission_shape",
        ),
        UniqueConstraint(
            "persistent_task_id",
            "idempotency_key",
            name="uq_persistent_task_triggers_task_idempotency",
        ),
        Index(
            "ix_persistent_task_triggers_pending",
            "persistent_task_id",
            "admitted_at",
            "observed_at",
        ),
        Index(
            "ix_persistent_task_triggers_turn",
            "admitted_turn_id",
        ),
    )

    id = Column(String(35), primary_key=True, default=lambda: _id("tg"))
    persistent_task_id = Column(
        String(35),
        ForeignKey("persistent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(16), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    observed_at = Column(DateTime, nullable=False, default=utc_now)
    source_identity = Column(String(256), nullable=False)
    source_version = Column(String(128), nullable=True)
    summary = Column(Text, nullable=False)
    cursor_after = Column(String(1_024), nullable=True)
    occurrence_fingerprint = Column(String(64), nullable=False)
    idempotency_key = Column(String(200), nullable=False)

    # The Conversation Turn is the run identity.  ``admitted_at`` prevents a
    # historical trigger from becoming pending again if retention later
    # removes the Turn row and SET NULL clears the optional correlation.
    admitted_turn_id = Column(
        String,
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    admitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "AUTOMATION_TRIGGER_KINDS",
    "PERSISTENT_TASK_STATES",
    "PERSISTENT_TASK_TRIGGER_KINDS",
    "PersistentTask",
    "PersistentTaskTrigger",
]
