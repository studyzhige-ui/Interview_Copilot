"""Owner-scoped read projection for durable Tool audit details."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent_runtime.tool_redaction import (
    bounded_tool_result_projection,
    redact_tool_text,
    redact_tool_value,
)
from app.models.agent_execution import AgentToolCall
from app.models.conversation_turn import ConversationTurn
from app.schemas.tool_call_audit import AgentToolCallAuditView


class ToolCallAuditNotFoundError(LookupError):
    """The Turn/Tool Call does not exist within the authenticated owner scope."""


def get_tool_call_audit(
    db: Session,
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    call_id: str,
) -> AgentToolCallAuditView:
    """Return a defense-in-depth redacted view of one canonical Tool Call."""

    turn = (
        db.query(ConversationTurn.id)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.user_id == user_id,
        )
        .one_or_none()
    )
    if turn is None:
        raise ToolCallAuditNotFoundError("Tool Call not found")

    row = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.turn_id == turn_id,
            AgentToolCall.session_id == conversation_id,
            AgentToolCall.user_id == user_id,
            AgentToolCall.call_id == call_id,
        )
        .one_or_none()
    )
    if row is None:
        raise ToolCallAuditNotFoundError("Tool Call not found")

    arguments = redact_tool_value(row.arguments_json or {})
    if not isinstance(arguments, dict):
        arguments = {}
    result = bounded_tool_result_projection(row.result_json)
    error = redact_tool_text(row.error) if row.error else None
    timeline = redact_tool_value(row.timeline_json or [])
    if not isinstance(timeline, list):
        timeline = []
    receipt_refs = [
        redact_tool_text(str(value)) for value in (row.receipt_refs_json or []) if value
    ]
    resource_identities = [
        redact_tool_text(str(value))[:255]
        for value in (row.resource_identities_json or [])[:32]
        if value
    ]
    return AgentToolCallAuditView(
        call_id=row.call_id,
        turn_id=row.turn_id,
        tool_name=row.tool_name,
        effect=row.effect,
        status=row.status,
        dispatch_generation=row.dispatch_generation,
        policy_decision=row.policy_decision,
        policy_reason=row.policy_reason,
        model_step=row.model_step,
        model_call_index=row.model_call_index,
        model_call_order=row.model_call_order,
        completion_sequence=row.completion_sequence,
        handler_identity=(
            redact_tool_text(row.handler_identity) if row.handler_identity else None
        ),
        provider_identity=(
            redact_tool_text(row.provider_identity) if row.provider_identity else None
        ),
        connection_identity=(
            redact_tool_text(row.connection_identity)
            if row.connection_identity
            else None
        ),
        timeline=[item for item in timeline if isinstance(item, dict)],
        receipt_refs=receipt_refs,
        resource_identities=resource_identities,
        arguments=arguments,
        result=result,
        error=error,
        timeout_seconds=row.timeout_seconds,
        duration_ms=row.duration_ms,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


__all__ = ["ToolCallAuditNotFoundError", "get_tool_call_audit"]
