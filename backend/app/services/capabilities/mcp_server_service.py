from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.edition import current_edition_policy
from app.core.secrets import decrypt_secret, encrypt_secret
from app.db.types import utc_now
from app.models.user_mcp_server import UserMCPServer


@dataclass(frozen=True)
class MCPServerConfig:
    id: int
    name: str
    transport: str
    url: str | None
    command: str | None
    args: list[str]
    headers: dict[str, str]
    env: dict[str, str]
    revision: str
    user_id: int = 0


def _encode_secrets(headers: dict[str, str], env: dict[str, str]) -> str | None:
    payload = {"headers": headers, "env": env}
    if not headers and not env:
        return None
    return encrypt_secret(json.dumps(payload, ensure_ascii=False))


def _decode_secrets(ciphertext: str | None) -> tuple[dict[str, str], dict[str, str]]:
    if not ciphertext:
        return {}, {}
    plaintext = decrypt_secret(ciphertext)
    if plaintext is None:
        raise ValueError("MCP server secrets cannot be decrypted")
    payload = json.loads(plaintext)
    return dict(payload.get("headers") or {}), dict(payload.get("env") or {})


def validate_transport(transport: str) -> None:
    policy = current_edition_policy()
    if transport not in policy.supported_mcp_transports:
        raise ValueError(f"{transport} MCP is not available in {policy.display_name}")
    if transport == "stdio" and not settings.MCP_ALLOW_STDIO:
        raise ValueError("stdio MCP is disabled by this Community deployment")


def _payload(row: UserMCPServer) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "transport": row.transport,
        "url": row.url,
        "command": row.command,
        "args": list(row.args_json or []),
        "has_secrets": bool(row.secrets_ciphertext),
        "enabled": row.enabled,
        "last_status": row.last_status,
        "last_error": row.last_error,
        "tool_count": row.tool_count,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_servers(
    db: Session, user_pk: int, *, enabled_only: bool = False
) -> list[dict]:
    query = db.query(UserMCPServer).filter(UserMCPServer.user_id == user_pk)
    if enabled_only:
        query = query.filter(UserMCPServer.enabled.is_(True))
    return [_payload(row) for row in query.order_by(UserMCPServer.name).all()]


def get_server(db: Session, user_pk: int, server_id: int) -> UserMCPServer | None:
    return (
        db.query(UserMCPServer)
        .filter(
            UserMCPServer.id == server_id,
            UserMCPServer.user_id == user_pk,
        )
        .one_or_none()
    )


def create_server(db: Session, user_pk: int, data: dict) -> dict:
    validate_transport(data["transport"])
    if (
        db.query(UserMCPServer.id)
        .filter(
            UserMCPServer.user_id == user_pk,
            UserMCPServer.name == data["name"],
        )
        .first()
    ):
        raise ValueError(f"MCP server '{data['name']}' already exists")
    row = UserMCPServer(
        user_id=user_pk,
        name=data["name"],
        transport=data["transport"],
        url=data.get("url"),
        command=data.get("command"),
        args_json=data.get("args") or [],
        secrets_ciphertext=_encode_secrets(
            data.get("headers") or {}, data.get("env") or {}
        ),
        enabled=data.get("enabled", True),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _payload(row)


def update_server(db: Session, user_pk: int, server_id: int, data: dict) -> dict | None:
    validate_transport(data["transport"])
    row = get_server(db, user_pk, server_id)
    if row is None:
        return None
    duplicate = (
        db.query(UserMCPServer.id)
        .filter(
            UserMCPServer.user_id == user_pk,
            UserMCPServer.name == data["name"],
            UserMCPServer.id != server_id,
        )
        .first()
    )
    if duplicate:
        raise ValueError(f"MCP server '{data['name']}' already exists")
    row.name = data["name"]
    row.transport = data["transport"]
    row.url = data.get("url")
    row.command = data.get("command")
    row.args_json = data.get("args") or []
    row.enabled = data.get("enabled", True)
    if data.get("headers") is not None or data.get("env") is not None:
        old_headers, old_env = _decode_secrets(row.secrets_ciphertext)
        row.secrets_ciphertext = _encode_secrets(
            old_headers if data.get("headers") is None else data["headers"],
            old_env if data.get("env") is None else data["env"],
        )
    row.last_status = "unchecked"
    row.last_error = None
    row.tool_count = 0
    row.checked_at = None
    db.commit()
    db.refresh(row)
    return _payload(row)


def set_enabled(
    db: Session, user_pk: int, server_id: int, enabled: bool
) -> dict | None:
    row = get_server(db, user_pk, server_id)
    if row is None:
        return None
    row.enabled = enabled
    db.commit()
    db.refresh(row)
    return _payload(row)


def delete_server(db: Session, user_pk: int, server_id: int) -> bool:
    row = get_server(db, user_pk, server_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def config_for(row: UserMCPServer) -> MCPServerConfig:
    validate_transport(row.transport)
    headers, env = _decode_secrets(row.secrets_ciphertext)
    return MCPServerConfig(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        transport=row.transport,
        url=row.url,
        command=row.command,
        args=list(row.args_json or []),
        headers=headers,
        env=env,
        revision=row.updated_at.isoformat() if row.updated_at else "",
    )


def enabled_configs(db: Session, user_pk: int) -> list[MCPServerConfig]:
    transports = set(current_edition_policy().supported_mcp_transports)
    if not settings.MCP_ALLOW_STDIO:
        transports.discard("stdio")
    rows = (
        db.query(UserMCPServer)
        .filter(
            UserMCPServer.user_id == user_pk,
            UserMCPServer.enabled.is_(True),
            UserMCPServer.transport.in_(transports),
        )
        .order_by(UserMCPServer.name)
        .all()
    )
    return [config_for(row) for row in rows]


def record_check(
    db: Session,
    user_pk: int,
    server_id: int,
    *,
    status: str,
    error: str | None,
    tool_count: int,
) -> dict | None:
    row = get_server(db, user_pk, server_id)
    if row is None:
        return None
    row.last_status = status
    row.last_error = error
    row.tool_count = tool_count
    row.checked_at = utc_now()
    db.commit()
    db.refresh(row)
    return _payload(row)
