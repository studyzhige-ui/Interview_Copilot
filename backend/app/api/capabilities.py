from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.agent_runtime.mcp import manager
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.capabilities import (
    CapabilityEnabledRequest,
    MCPServerConfigRequest,
    SessionCapabilityPermissionRequest,
    SkillCreateRequest,
    SkillUpdateRequest,
)
from app.services.capabilities import (
    conversation_capability_service,
    mcp_server_service,
    skill_service,
)


router = APIRouter(prefix="/capabilities", tags=["capabilities"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/edition")
def get_edition_policy():
    from app.core.config import settings
    from app.core.edition import current_edition_policy

    return current_edition_policy().public_payload(
        stdio_enabled=settings.MCP_ALLOW_STDIO,
    )


@router.get("/sessions/{session_id}")
def get_session_capabilities(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = conversation_capability_service.get_or_create(
            db, session_id, current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return conversation_capability_service.payload(row)


@router.put("/sessions/{session_id}/permissions")
def set_session_capability_permission(
    session_id: str,
    payload: SessionCapabilityPermissionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = conversation_capability_service.get_or_create(
            db, session_id, current_user.id
        )
        conversation_capability_service.validate_capability(
            db,
            current_user.id,
            payload.capability,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "Conversation not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return conversation_capability_service.set_permission(
        db,
        row,
        payload.capability,
        payload.decision,
    )


@router.get("/skills")
def list_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"skills": skill_service.list_skills(db, current_user.id)}


@router.post("/skills", status_code=status.HTTP_201_CREATED)
def create_skill(
    payload: SkillCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return skill_service.create_skill(
            db, current_user.id, payload.content, payload.enabled
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/skills/{skill_id}")
def update_skill(
    skill_id: int,
    payload: SkillUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = skill_service.update_skill(
            db,
            current_user.id,
            skill_id,
            content=payload.content,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return result


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not skill_service.delete_skill(db, current_user.id, skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mcp-servers")
def list_mcp_servers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    servers = mcp_server_service.list_servers(db, current_user.id)
    for server in servers:
        runtime = manager.status(current_user.id, server["id"])
        if runtime:
            server["runtime"] = runtime
    return {"servers": servers}


@router.post("/mcp-servers", status_code=status.HTTP_201_CREATED)
def create_mcp_server(
    payload: MCPServerConfigRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return mcp_server_service.create_server(
            db,
            current_user.id,
            payload.model_dump(),
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.put("/mcp-servers/{server_id}")
async def update_mcp_server(
    server_id: int,
    payload: MCPServerConfigRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = mcp_server_service.update_server(
            db,
            current_user.id,
            server_id,
            payload.model_dump(),
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await manager.invalidate(current_user.id, server_id)
    return result


@router.patch("/mcp-servers/{server_id}/enabled")
async def set_mcp_server_enabled(
    server_id: int,
    payload: CapabilityEnabledRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = mcp_server_service.set_enabled(
        db, current_user.id, server_id, payload.enabled
    )
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await manager.invalidate(current_user.id, server_id)
    return result


@router.post("/mcp-servers/{server_id}/test")
async def test_mcp_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = mcp_server_service.get_server(db, current_user.id, server_id)
    if row is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    try:
        tools = await manager.list_tools(mcp_server_service.config_for(row), force=True)
    except Exception as exc:
        mcp_server_service.record_check(
            db,
            current_user.id,
            server_id,
            status="failed",
            error=str(exc),
            tool_count=0,
        )
        raise HTTPException(
            status_code=400, detail=f"MCP connection failed: {exc}"
        ) from exc
    server = mcp_server_service.record_check(
        db,
        current_user.id,
        server_id,
        status="connected",
        error=None,
        tool_count=len(tools),
    )
    return {
        "server": server,
        "tools": [
            {"name": tool.name, "description": tool.description} for tool in tools
        ],
    }


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not mcp_server_service.delete_server(db, current_user.id, server_id):
        raise HTTPException(status_code=404, detail="MCP server not found")
    await manager.invalidate(current_user.id, server_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
