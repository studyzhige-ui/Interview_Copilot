"""Bounded exact search over the canonical Interaction Records.

This service does not create a History index owner or reinterpret old content
as current fact.  It returns stable record identities and exact, redacted
excerpts from ConversationMessage and AgentToolCall.
"""

from __future__ import annotations

import json

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.agent_runtime.tool_redaction import redact_tool_text
from app.agent_runtime.tool_redaction import redact_tool_value
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.schemas.history_search import (
    HistoryRecordDetail,
    HistorySearchQuery,
    HistorySearchResponse,
    HistorySearchResult,
)


class HistorySearchNotFoundError(ValueError):
    pass


def get_interaction_history_record(
    db: Session,
    *,
    user_pk: int,
    identity: str,
) -> HistoryRecordDetail:
    """Read one full, redacted canonical record by its stable identity.

    Search is only a locator. Exact past wording and Tool input/result require
    this owner-checked read and are never reconstructed from the excerpt.
    """

    if identity.startswith("conversation_message:"):
        raw_id = identity.removeprefix("conversation_message:")
        if not raw_id.isdigit():
            raise HistorySearchNotFoundError("History record not found")
        found = (
            db.query(ConversationMessage, Conversation)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .filter(
                ConversationMessage.id == int(raw_id),
                Conversation.user_id == user_pk,
            )
            .one_or_none()
        )
        if found is None:
            raise HistorySearchNotFoundError("History record not found")
        message, conversation = found
        blocks = redact_tool_value(list(message.content_blocks_json or []))
        safe_blocks = blocks if isinstance(blocks, list) else []
        turn = (
            db.query(ConversationTurn)
            .filter(
                ConversationTurn.conversation_id == conversation.id,
                ConversationTurn.user_id == user_pk,
                ConversationTurn.user_message_seq == message.seq,
            )
            .one_or_none()
        )
        if turn is not None:
            attachment_refs = (
                db.query(ConversationAttachmentRef)
                .filter(
                    ConversationAttachmentRef.turn_id == turn.id,
                    ConversationAttachmentRef.user_id == user_pk,
                )
                .order_by(ConversationAttachmentRef.position)
                .all()
            )
            safe_blocks = [
                *safe_blocks,
                *[
                    {
                        "type": "attachment_ref",
                        "attachment_ref_id": ref.id,
                        "file_asset_id": ref.file_asset_id,
                        "file_asset_version": ref.file_asset_version,
                        "display_name": ref.display_name,
                        "scope": "conversation",
                        "accessible": ref.removed_at is None,
                        "removed_at": ref.removed_at.isoformat()
                        if ref.removed_at
                        else None,
                    }
                    for ref in attachment_refs
                ],
            ]
        return HistoryRecordDetail(
            kind="message",
            identity=identity,
            conversation_id=conversation.id,
            conversation_title=conversation.title or "",
            conversation_type=conversation.type or "general",
            turn_id=turn.id if turn is not None else None,
            message_id=message.id,
            seq=int(message.seq),
            role=_normalize_role(message.role),
            tool_call_id=message.tool_call_id,
            tool_name=message.tool_name,
            tool_status=None,
            occurred_at=message.created_at,
            content=redact_tool_text(str(message.content or "")),
            content_blocks=safe_blocks,
        )

    if identity.startswith("agent_tool_call:"):
        parts = identity.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise HistorySearchNotFoundError("History record not found")
        turn_id, call_id = parts[1], parts[2]
        found = (
            db.query(AgentToolCall, ConversationTurn, Conversation)
            .join(ConversationTurn, ConversationTurn.id == AgentToolCall.turn_id)
            .join(Conversation, Conversation.id == AgentToolCall.session_id)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.call_id == call_id,
                AgentToolCall.user_id == user_pk,
                Conversation.user_id == user_pk,
            )
            .one_or_none()
        )
        if found is None:
            raise HistorySearchNotFoundError("History record not found")
        call, turn, conversation = found
        arguments = redact_tool_value(dict(call.arguments_json or {}))
        result = (
            redact_tool_value(dict(call.result_json or {}))
            if call.result_json
            else None
        )
        return HistoryRecordDetail(
            kind="tool_call",
            identity=identity,
            conversation_id=conversation.id,
            conversation_title=conversation.title or "",
            conversation_type=conversation.type or "general",
            turn_id=turn.id,
            message_id=None,
            seq=None,
            role="tool",
            tool_call_id=call.call_id,
            tool_name=call.tool_name,
            tool_status=call.status,
            occurred_at=call.completed_at or call.started_at,
            arguments=arguments if isinstance(arguments, dict) else {},
            result=result if isinstance(result, dict) else None,
            error=redact_tool_text(str(call.error)) if call.error else None,
        )

    raise HistorySearchNotFoundError("History record not found")


def search_interaction_history(
    db: Session,
    *,
    user_pk: int,
    request: HistorySearchQuery,
) -> HistorySearchResponse:
    conversation_id = request.conversation_id
    if conversation_id is not None:
        owned = (
            db.query(Conversation.id)
            .filter(
                Conversation.id == conversation_id,
                Conversation.user_id == user_pk,
            )
            .scalar()
        )
        if owned is None:
            raise HistorySearchNotFoundError("Conversation not found")

    pattern = f"%{_escape_like(request.query)}%"
    candidates: list[HistorySearchResult] = []
    fetch_limit = min(100, request.limit * 3)
    if "message" in request.kinds:
        query = (
            db.query(ConversationMessage, Conversation)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .filter(
                Conversation.user_id == user_pk,
                or_(
                    ConversationMessage.content.ilike(pattern, escape="\\"),
                    ConversationMessage.content_blocks_json.ilike(pattern, escape="\\"),
                ),
            )
        )
        if conversation_id is not None:
            query = query.filter(Conversation.id == conversation_id)
        if request.roles:
            query = query.filter(
                ConversationMessage.role.ilike(request.roles[0])
                if len(request.roles) == 1
                else or_(
                    *[ConversationMessage.role.ilike(role) for role in request.roles]
                )
            )
        for message, conversation in (
            query.order_by(
                ConversationMessage.created_at.desc(), ConversationMessage.id.desc()
            )
            .limit(fetch_limit)
            .all()
        ):
            candidates.append(
                HistorySearchResult(
                    kind="message",
                    identity=f"conversation_message:{message.id}",
                    conversation_id=conversation.id,
                    conversation_title=conversation.title or "",
                    conversation_type=conversation.type or "general",
                    turn_id=None,
                    message_id=message.id,
                    seq=int(message.seq),
                    role=_normalize_role(message.role),
                    tool_call_id=message.tool_call_id,
                    tool_name=message.tool_name,
                    tool_status=None,
                    occurred_at=message.created_at,
                    excerpt=_message_excerpt(message, request.query),
                )
            )

    if "tool_call" in request.kinds:
        tool_query = (
            db.query(AgentToolCall, ConversationTurn, Conversation)
            .join(ConversationTurn, ConversationTurn.id == AgentToolCall.turn_id)
            .join(Conversation, Conversation.id == AgentToolCall.session_id)
            .filter(
                AgentToolCall.user_id == user_pk,
                Conversation.user_id == user_pk,
                or_(
                    AgentToolCall.tool_name.ilike(pattern, escape="\\"),
                    AgentToolCall.status.ilike(pattern, escape="\\"),
                    AgentToolCall.error.ilike(pattern, escape="\\"),
                    cast(AgentToolCall.arguments_json, String).ilike(
                        pattern, escape="\\"
                    ),
                    cast(AgentToolCall.result_json, String).ilike(pattern, escape="\\"),
                ),
            )
        )
        if conversation_id is not None:
            tool_query = tool_query.filter(Conversation.id == conversation_id)
        for call, turn, conversation in (
            tool_query.order_by(
                AgentToolCall.started_at.desc(), AgentToolCall.id.desc()
            )
            .limit(fetch_limit)
            .all()
        ):
            candidates.append(
                HistorySearchResult(
                    kind="tool_call",
                    identity=f"agent_tool_call:{turn.id}:{call.call_id}",
                    conversation_id=conversation.id,
                    conversation_title=conversation.title or "",
                    conversation_type=conversation.type or "general",
                    turn_id=turn.id,
                    message_id=None,
                    seq=None,
                    role="tool",
                    tool_call_id=call.call_id,
                    tool_name=call.tool_name,
                    tool_status=call.status,
                    occurred_at=call.completed_at or call.started_at,
                    excerpt=_tool_excerpt(call, request.query),
                )
            )

    selected = sorted(
        candidates,
        key=lambda item: (item.occurred_at, item.identity),
        reverse=True,
    )[: request.limit]
    return HistorySearchResponse(
        query=request.query,
        count=len(selected),
        results=selected,
    )


def _message_excerpt(message: ConversationMessage, needle: str) -> str:
    content = str(message.content or "")
    if not content and message.content_blocks_json:
        content = str(message.content_blocks_json)
    return _excerpt(redact_tool_text(content), needle)


def _tool_excerpt(call: AgentToolCall, needle: str) -> str:
    content = json.dumps(
        {
            "tool": call.tool_name,
            "status": call.status,
            "arguments": call.arguments_json or {},
            "result": call.result_json,
            "error": call.error,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return _excerpt(redact_tool_text(content), needle)


def _excerpt(content: str, needle: str, radius: int = 500) -> str:
    compact = " ".join(content.split())
    if len(compact) <= radius * 2:
        return compact
    position = compact.casefold().find(needle.casefold())
    if position < 0:
        return compact[: radius * 2] + "…"
    start = max(0, position - radius)
    end = min(len(compact), position + len(needle) + radius)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end] + suffix


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_role(value: str) -> str:
    normalized = str(value or "").casefold()
    return "assistant" if normalized == "agent" else normalized


__all__ = [
    "HistorySearchNotFoundError",
    "get_interaction_history_record",
    "search_interaction_history",
]
