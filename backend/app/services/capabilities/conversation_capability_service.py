from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.chat import Conversation
from app.models.conversation_capability_state import ConversationCapabilityState
from app.models.user_mcp_server import UserMCPServer
from app.models.user_skill import UserSkill


_HISTORY_LIMIT = 50
_DISCOVERY_TOOLS = {"skill_search", "skill_load", "tool_search"}


def validate_capability(db: Session, user_id: int, capability: str) -> None:
    if capability in _DISCOVERY_TOOLS:
        return
    if capability.startswith("skill:"):
        name = capability.removeprefix("skill:")
        exists = (
            db.query(UserSkill.id)
            .filter(
                UserSkill.user_id == user_id,
                UserSkill.name == name,
            )
            .first()
        )
    elif capability.startswith("mcp_server:"):
        raw_id = capability.removeprefix("mcp_server:")
        exists = (
            raw_id.isdigit()
            and db.query(UserMCPServer.id)
            .filter(
                UserMCPServer.user_id == user_id,
                UserMCPServer.id == int(raw_id),
            )
            .first()
        )
    else:
        from app.agent_runtime.tool_registry import registry

        exists = capability in registry
    if not exists:
        raise ValueError("Capability not found")


def get_or_create(
    db: Session,
    conversation_id: str,
    user_id: int,
) -> ConversationCapabilityState:
    conversation = (
        db.query(Conversation.id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .one_or_none()
    )
    if conversation is None:
        raise ValueError("Conversation not found")
    row = db.get(ConversationCapabilityState, conversation_id)
    if row is None:
        row = ConversationCapabilityState(
            conversation_id=conversation_id, user_id=user_id
        )
        db.add(row)
        db.flush()
    return row


def payload(row: ConversationCapabilityState) -> dict:
    return {
        "conversation_id": row.conversation_id,
        "discovered_skills": list(row.discovered_skills_json or []),
        "permissions": dict(row.permissions_json or {}),
        "tool_history": list(row.tool_history_json or []),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def permission_for(
    row: ConversationCapabilityState,
    tool_name: str,
    *,
    server_id: int | None = None,
) -> str:
    permissions = dict(row.permissions_json or {})
    return (
        permissions.get(tool_name)
        or (
            permissions.get(f"mcp_server:{server_id}")
            if server_id is not None
            else None
        )
        or "allow"
    )


def set_permission(
    db: Session,
    row: ConversationCapabilityState,
    capability: str,
    decision: str,
) -> dict:
    permissions = dict(row.permissions_json or {})
    if decision == "inherit":
        permissions.pop(capability, None)
    else:
        permissions[capability] = decision
    row.permissions_json = permissions
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return payload(row)


def record_discovered_skills(
    db: Session,
    row: ConversationCapabilityState,
    names: list[str],
) -> None:
    discovered = list(row.discovered_skills_json or [])
    seen = set(discovered)
    for name in names:
        if name not in seen:
            discovered.append(name)
            seen.add(name)
    row.discovered_skills_json = discovered
    row.updated_at = datetime.utcnow()
    db.commit()


def append_tool_history(
    db: Session,
    row: ConversationCapabilityState,
    *,
    tool_name: str,
    status: str,
    turn_id: str,
) -> None:
    history = list(row.tool_history_json or [])
    history.append(
        {
            "tool_name": tool_name,
            "status": status,
            "turn_id": turn_id,
            "at": datetime.utcnow().isoformat(),
        }
    )
    row.tool_history_json = history[-_HISTORY_LIMIT:]
    row.updated_at = datetime.utcnow()
