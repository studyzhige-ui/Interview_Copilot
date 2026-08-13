from __future__ import annotations

import asyncio
import json
from collections.abc import Collection
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, Field

from app.agent_runtime.mcp import MCPToolDescriptor, manager
from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolRegistryView,
    _pydantic_to_openai_schema,
    registry,
)
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.conversation_turn import ConversationTurn
from app.services.capabilities import (
    mcp_server_service,
    skill_service,
)


# Remote MCP remains configurable/testable through the capability API, but it
# is not an Agent callable until its approval/resume path can execute the same
# call identity exactly once.  Fail closed instead of advertising a Tool that
# can only loop on ``policy_required``.
_MCP_AGENT_EXECUTION_ENABLED = False


class _SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class _LoadSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64)


def cloud_sustainable_read_tool_names() -> frozenset[str]:
    """Concrete built-ins eligible for unattended cloud execution now."""

    snapshot = registry.snapshot()
    return frozenset(
        name
        for name in snapshot.tool_names
        if snapshot.effect_for(name) is ToolEffect.READ
    )


@dataclass
class _LoadedState:
    mcp: dict[str, MCPToolDescriptor] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnToolCatalog:
    """Immutable per-turn view of real tools and deferred tool descriptors."""

    builtins: ToolRegistryView
    excluded: frozenset[str]
    user_id: str
    user_pk: int
    session_id: str
    turn_id: str | None
    skills: tuple[dict, ...]
    mcp_tools: tuple[MCPToolDescriptor, ...]
    mcp_configs: Mapping[int, mcp_server_service.MCPServerConfig]
    loaded: _LoadedState = field(default_factory=_LoadedState, compare=False)

    @classmethod
    async def create(
        cls,
        user_id: str,
        *,
        session_id: str = "",
        turn_id: str | None = None,
        exclude: set[str] | None = None,
        builtin_allowlist: Collection[str] | None = None,
        include_deferred: bool = True,
    ) -> "TurnToolCatalog":
        """Freeze the concrete tool surface for one execution pass.

        Unattended PersistentTask turns pass an explicit built-in allowlist
        and disable deferred capabilities.  That keeps the normal Agent path
        unchanged while ensuring an automation cannot discover MCP, Skills,
        client actions, or a built-in added after the task was saved.
        """

        def load():
            db = SessionLocal()
            try:
                user_pk = resolve_user_pk(db, user_id)
                if user_pk is None:
                    return None
                if not include_deferred:
                    return user_pk, [], []
                return (
                    user_pk,
                    skill_service.list_skills(
                        db,
                        user_pk,
                        enabled_only=True,
                        include_content=False,
                    ),
                    (
                        mcp_server_service.enabled_configs(db, user_pk)
                        if _MCP_AGENT_EXECUTION_ENABLED
                        else []
                    ),
                )
            finally:
                db.close()

        loaded = await asyncio.to_thread(load)
        if loaded is None:
            user_pk, skills, configs = 0, [], []
        else:
            user_pk, skills, configs = loaded
        tools, _failures = (
            await manager.discover(configs) if include_deferred else ([], [])
        )

        effective_exclude = set(exclude or set())
        if builtin_allowlist is not None:
            effective_exclude.update(set(registry.tool_names) - set(builtin_allowlist))

        catalog = cls(
            builtins=registry.snapshot(exclude=effective_exclude, user_id=user_id),
            excluded=frozenset(effective_exclude),
            user_id=user_id,
            user_pk=user_pk,
            session_id=session_id,
            turn_id=turn_id,
            skills=tuple(
                sorted(
                    (dict(row) for row in skills),
                    key=lambda row: (str(row["name"]), int(row["id"])),
                )
            ),
            mcp_tools=tuple(
                sorted(tools, key=lambda tool: (tool.name, tool.server_id))
            ),
            mcp_configs=MappingProxyType(
                {
                    config.id: config
                    for config in sorted(configs, key=lambda config: config.id)
                }
            ),
        )
        await catalog._persist_snapshot()
        return catalog

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        schemas = list(self.builtins.get_openai_schemas())
        if self.skills:
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_search",
                    "Search the current user's enabled skills by purpose.",
                    _SearchArgs,
                )
            )
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_load",
                    "Load the full instructions for one enabled skill.",
                    _LoadSkillArgs,
                )
            )
        if _MCP_AGENT_EXECUTION_ENABLED and self.mcp_tools:
            schemas.append(
                _pydantic_to_openai_schema(
                    "tool_search",
                    "Load matching deferred MCP tool schemas before calling them.",
                    _SearchArgs,
                )
            )
        if _MCP_AGENT_EXECUTION_ENABLED:
            schemas.extend(self._mcp_schema(tool) for tool in self.loaded.mcp.values())
        return sorted(schemas, key=lambda schema: schema["function"]["name"])

    @staticmethod
    def _mcp_schema(tool: MCPToolDescriptor) -> dict[str, Any]:
        parameters = dict(tool.input_schema)
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": parameters,
            },
        }

    def format_prompt(self) -> str:
        parts = [self.builtins.format_guidance().strip()]
        skills = sorted(
            [
                {"name": row["name"], "description": row["description"]}
                for row in self.skills
            ],
            key=lambda row: row["name"],
        )
        if skills:
            parts.append(
                "Enabled user skill index (use skill_search/skill_load when useful):\n"
                + json.dumps(
                    skills,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        mcp_tools = sorted(
            [
                {"name": tool.name, "description": tool.description}
                for tool in self.mcp_tools
            ],
            key=lambda row: row["name"],
        )
        if _MCP_AGENT_EXECUTION_ENABLED and mcp_tools:
            parts.append(
                "Deferred MCP tool index (use tool_search to load concrete schemas):\n"
                + json.dumps(
                    mcp_tools,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        return "\n\n".join(part for part in parts if part)

    def __contains__(self, name: str) -> bool:
        if name in {"skill_search", "skill_load"} and self.skills:
            return True
        if name == "tool_search" and _MCP_AGENT_EXECUTION_ENABLED and self.mcp_tools:
            return True
        if _MCP_AGENT_EXECUTION_ENABLED and name in self.loaded.mcp:
            return True
        return name not in self.excluded and name in self.builtins

    def is_concurrency_safe(self, name: str) -> bool:
        """Return true only for an explicitly safe built-in tool.

        Skill discovery and MCP tools have unknown side effects, so both remain
        serial until concrete execution policy supplies stronger annotations.
        """
        return name not in self.excluded and self.builtins.is_concurrency_safe(name)

    def effect_for(self, name: str) -> ToolEffect:
        if name in {"skill_search", "skill_load", "tool_search"}:
            return ToolEffect.READ
        if _MCP_AGENT_EXECUTION_ENABLED and (
            name in self.loaded.mcp
            or any(descriptor.name == name for descriptor in self.mcp_tools)
        ):
            return ToolEffect.UNKNOWN
        if name in self.excluded:
            return ToolEffect.UNKNOWN
        return self.builtins.effect_for(name)

    def policy_traits(
        self,
        name: str,
        arguments: dict,
        ctx: AgentToolContext,
        current_task: str,
    ) -> tuple[bool, bool]:
        # Deferred discovery and MCP descriptors are deliberately conservative:
        # no task authorizer exists until a concrete, reviewed definition does.
        if name in {"skill_search", "skill_load", "tool_search"}:
            return False, False
        if _MCP_AGENT_EXECUTION_ENABLED and (
            name in self.loaded.mcp
            or any(descriptor.name == name for descriptor in self.mcp_tools)
        ):
            return False, False
        if name in self.excluded:
            return False, False
        return self.builtins.policy_traits(name, arguments, ctx, current_task)

    async def dispatch(self, name: str, raw_args: dict, ctx: AgentToolContext) -> dict:
        if name == "skill_search" and self.skills:
            args = _SearchArgs.model_validate(raw_args)
            matches = skill_service.search(list(self.skills), args.query)
            return {
                "skills": [
                    {"name": row["name"], "description": row["description"]}
                    for row in matches
                ]
            }
        if name == "skill_load" and self.skills:
            args = _LoadSkillArgs.model_validate(raw_args)
            row = await self._load_skill(args.name)
            if row is None:
                return {"error": "skill_not_found", "name": args.name}
            if row.get("error"):
                return row
            return {
                "name": row["name"],
                "description": row["description"],
                "instructions": row["content"],
            }
        if name == "tool_search" and _MCP_AGENT_EXECUTION_ENABLED and self.mcp_tools:
            args = _SearchArgs.model_validate(raw_args)
            matches = self._search_mcp(args.query)
            self.loaded.mcp.update((tool.name, tool) for tool in matches)
            await self._persist_loaded_schemas()
            return {
                "loaded_tools": [
                    {"name": tool.name, "description": tool.description}
                    for tool in matches
                ]
            }
        if _MCP_AGENT_EXECUTION_ENABLED:
            tool = self.loaded.mcp.get(name)
            if tool is not None:
                return {"error": "policy_required", "tool_name": name}
            if any(descriptor.name == name for descriptor in self.mcp_tools):
                return {"error": "policy_required", "tool_name": name}
        return await self.builtins.dispatch(name, raw_args, ctx)

    def _search_mcp(self, query: str) -> list[MCPToolDescriptor]:
        needle = query.casefold().strip()
        available = sorted(
            self.mcp_tools,
            key=lambda tool: (tool.name, tool.server_id),
        )
        exact = [tool for tool in available if tool.name.casefold() == needle]
        if exact:
            return exact
        terms = needle.split()
        matches = [
            tool
            for tool in available
            if needle in f"{tool.name} {tool.description}".casefold()
            or all(
                term in f"{tool.name} {tool.description}".casefold() for term in terms
            )
        ]
        return matches[:5]

    async def _load_skill(self, name: str) -> dict | None:
        snapshot = next((row for row in self.skills if row["name"] == name), None)
        if snapshot is None:
            return None

        def load():
            db = SessionLocal()
            try:
                row = skill_service.get_skill(db, self.user_pk, snapshot["id"])
                if row is None or row.name != snapshot["name"]:
                    return None
                revision = row.updated_at.isoformat() if row.updated_at else None
                if revision != snapshot["updated_at"]:
                    return {
                        "error": "skill_revision_changed",
                        "name": name,
                    }
                return {
                    "name": row.name,
                    "description": row.description,
                    "content": row.content,
                }
            finally:
                db.close()

        return await asyncio.to_thread(load)

    async def _persist_snapshot(self) -> None:
        if not self.turn_id:
            return
        tool_snapshot = {
            "tools": {
                "builtins": [
                    name
                    for name in self.builtins.tool_names
                    if name not in self.excluded
                ],
                "mcp": [
                    {
                        "name": tool.name,
                        "server_id": tool.server_id,
                        "remote_name": tool.remote_name,
                    }
                    for tool in sorted(
                        self.mcp_tools if _MCP_AGENT_EXECUTION_ENABLED else (),
                        key=lambda item: (item.name, item.server_id),
                    )
                ],
            },
            "skills": [
                {"id": row["id"], "name": row["name"], "revision": row["updated_at"]}
                for row in sorted(self.skills, key=lambda item: item["name"])
            ],
            "mcp_servers": [
                {"id": config.id, "name": config.name, "revision": config.revision}
                for config in sorted(
                    (self.mcp_configs.values() if _MCP_AGENT_EXECUTION_ENABLED else ()),
                    key=lambda item: item.id,
                )
            ],
            "excluded": sorted(self.excluded),
        }

        def save() -> None:
            db = SessionLocal()
            try:
                row = db.get(ConversationTurn, self.turn_id)
                if row is not None and not row.tool_snapshot_json:
                    row.tool_snapshot_json = tool_snapshot
                    db.commit()
            finally:
                db.close()

        await asyncio.to_thread(save)

    async def _persist_loaded_schemas(self) -> None:
        if not self.turn_id:
            return
        schemas = sorted(
            (self._mcp_schema(tool) for tool in self.loaded.mcp.values()),
            key=lambda schema: schema["function"]["name"],
        )

        def save() -> None:
            db = SessionLocal()
            try:
                row = db.get(ConversationTurn, self.turn_id)
                if row is not None:
                    row.loaded_tool_schemas_json = schemas
                    db.commit()
            finally:
                db.close()

        await asyncio.to_thread(save)
