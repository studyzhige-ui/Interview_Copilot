"""Durable Shared Application Operation, verification, and domain-event records."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
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


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ApplicationOperation(Base):
    """One idempotent invocation of a versioned business operation."""

    __tablename__ = "application_operations"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user', 'agent_on_behalf', 'automation', "
            "'system_connector')",
            name="ck_application_operations_actor_kind",
        ),
        CheckConstraint(
            "status IN ('started', 'verifying', 'succeeded', 'failed', "
            "'unknown', 'reconciled')",
            name="ck_application_operations_status",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_application_operations_schema_version",
        ),
        UniqueConstraint(
            "user_id",
            "operation_name",
            "idempotency_key",
            name="uq_application_operations_user_name_idempotency",
        ),
        Index(
            "ix_application_operations_user_status_updated",
            "user_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_application_operations_turn_created",
            "turn_id",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("aop"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_name = Column(String(128), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    idempotency_key = Column(String(200), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    actor_kind = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="started")

    conversation_id = Column(
        String(36),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    turn_id = Column(
        String(36),
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id = Column(
        String(36),
        ForeignKey("agent_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_call_id = Column(String(256), nullable=True)
    interaction_id = Column(
        String(36),
        ForeignKey("agent_interactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    request_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime, nullable=True)


class OperationVerification(Base):
    """The durable truth check gating one Operation's success claim."""

    __tablename__ = "operation_verifications"
    __table_args__ = (
        CheckConstraint(
            "conclusion IN ('pending', 'verified', 'failed', 'unknown', 'reconciled')",
            name="ck_operation_verifications_conclusion",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_operation_verifications_schema_version",
        ),
        UniqueConstraint(
            "operation_id",
            name="uq_operation_verifications_operation",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("ver"))
    operation_id = Column(
        String(36),
        ForeignKey("application_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version = Column(Integer, nullable=False, default=1)
    conclusion = Column(String(20), nullable=False, default="pending")
    method = Column(String(64), nullable=False)
    expected_postconditions_json = Column(JSON, nullable=False, default=list)
    observed_evidence_json = Column(JSON, nullable=False, default=list)
    failure_reason = Column(Text, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    next_reconciliation_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime, nullable=True)


class CareerDomainEvent(Base):
    """Replayable event emitted by a committed Career Domain transaction."""

    __tablename__ = "career_domain_events"
    __table_args__ = (
        CheckConstraint(
            "event_category = 'domain'",
            name="ck_career_domain_events_category",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_career_domain_events_schema_version",
        ),
        CheckConstraint(
            "sequence >= 1",
            name="ck_career_domain_events_sequence",
        ),
        UniqueConstraint(
            "operation_id",
            "sequence",
            name="uq_career_domain_events_operation_sequence",
        ),
        UniqueConstraint(
            "user_id",
            "event_kind",
            "idempotency_key",
            name="uq_career_domain_events_user_kind_idempotency",
        ),
        Index(
            "ix_career_domain_events_user_occurred",
            "user_id",
            "occurred_at",
        ),
        Index(
            "ix_career_domain_events_aggregate",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: _id("cde"))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id = Column(
        String(36),
        ForeignKey("application_operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_kind = Column(String(128), nullable=False)
    event_category = Column(String(24), nullable=False, default="domain")
    schema_version = Column(Integer, nullable=False, default=1)
    sequence = Column(Integer, nullable=False)
    idempotency_key = Column(String(256), nullable=False)
    aggregate_type = Column(String(80), nullable=False)
    aggregate_id = Column(String(128), nullable=False)
    aggregate_version = Column(Integer, nullable=True)
    object_references_json = Column(JSON, nullable=False, default=list)
    payload_json = Column(JSON, nullable=False, default=dict)
    replayable = Column(Boolean, nullable=False, default=True)
    occurred_at = Column(DateTime, nullable=False, default=utc_now)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "ApplicationOperation",
    "CareerDomainEvent",
    "OperationVerification",
]
