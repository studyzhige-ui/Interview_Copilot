from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate as validate_json
from pydantic import BaseModel, Field

from app.agent_runtime.mcp import MCPToolDescriptor, manager
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
    conversation_capability_service,
    mcp_server_service,
    skill_service,
)


class _SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class _LoadSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64)


@dataclass
class _LoadedState:
    mcp: dict[str, MCPToolDescriptor] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnToolCatalog:
    """Immutable per-turn capability view plus explicitly persisted lazy state."""

    builtins: ToolRegistryView
    excluded: frozenset[str]
    user_id: str
    user_pk: int
    session_id: str
    turn_id: str | None
    skills: tuple[dict, ...]
    mcp_tools: tuple[MCPToolDescriptor, ...]
    mcp_configs: Mapping[int, mcp_server_service.MCPServerConfig]
    permissions: Mapping[str, str]
    tool_history: tuple[dict, ...]
    loaded: _LoadedState = field(default_factory=_LoadedState, compare=False)

    @classmethod
    async def create(
        cls,
        user_id: str,
        *,
        session_id: str = "",
        turn_id: str | None = None,
        exclude: set[str] | None = None,
    ) -> "TurnToolCatalog":
        def load():
            db = SessionLocal()
            try:
                user_pk = resolve_user_pk(db, user_id)
                if user_pk is None:
                    return None
                state_payload = {"permissions": {}, "tool_history": []}
                if session_id:
                    state = conversation_capability_service.get_or_create(
                        db, session_id, user_pk
                    )
                    state_payload = conversation_capability_service.payload(state)
                    db.commit()
                return (
                    user_pk,
                    skill_service.list_skills(
                        db,
                        user_pk,
                        enabled_only=True,
                        include_content=False,
                    ),
                    mcp_server_service.enabled_configs(db, user_pk),
                    state_payload,
                )
            finally:
                db.close()

        loaded = await asyncio.to_thread(load)
        if loaded is None:
            user_pk, skills, configs, session_state = (
                0,
                [],
                [],
                {
                    "permissions": {},
                    "tool_history": [],
                },
            )
        else:
            user_pk, skills, configs, session_state = loaded
        tools, _failures = await manager.discover(configs)
        permissions = dict(session_state["permissions"])

        catalog = cls(
            builtins=registry.snapshot(exclude=exclude, user_id=user_id),
            excluded=frozenset(exclude or set()),
            user_id=user_id,
            user_pk=user_pk,
            session_id=session_id,
            turn_id=turn_id,
            skills=tuple(dict(row) for row in skills),
            mcp_tools=tuple(tools),
            mcp_configs=MappingProxyType({config.id: config for config in configs}),
            permissions=MappingProxyType(permissions),
            tool_history=tuple(session_state["tool_history"]),
        )
        await catalog._persist_snapshot()
        return catalog

    def _decision(self, name: str, *, server_id: int | None = None) -> str:
        return (
            self.permissions.get(name)
            or (
                self.permissions.get(f"mcp_server:{server_id}")
                if server_id is not None
                else None
            )
            or "allow"
        )

    def _allowed(self, name: str, *, server_id: int | None = None) -> bool:
        return self._decision(name, server_id=server_id) == "allow"

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        schemas = [
            schema
            for schema in self.builtins.get_openai_schemas(
                exclude=set(self.excluded),
                user_id=self.user_id,
            )
            if self._allowed(schema["function"]["name"])
        ]
        if self.skills and self._allowed("skill_search"):
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_search",
                    "Search the current user's enabled skills by purpose.",
                    _SearchArgs,
                )
            )
        if self.skills and self._allowed("skill_load"):
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_load",
                    "Load the full instructions for one enabled skill.",
                    _LoadSkillArgs,
                )
            )
        if self.mcp_tools and self._allowed("tool_search"):
            schemas.append(
                _pydantic_to_openai_schema(
                    "tool_search",
                    "Load matching deferred MCP tool schemas before calling them.",
                    _SearchArgs,
                )
            )
        schemas.extend(
            self._mcp_schema(tool)
            for tool in self.loaded.mcp.values()
            if self._allowed(tool.name, server_id=tool.server_id)
        )
        return schemas

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
        denied_builtins = {
            name
            for name, decision in self.permissions.items()
            if decision == "deny" and name in self.builtins
        }
        builtin_manifest = json.loads(
            self.builtins.format_manifest(
                exclude=set(self.excluded) | denied_builtins,
                user_id=self.user_id,
            )
        )
        builtin_manifest = [
            row for row in builtin_manifest if self._allowed(row["name"])
        ]
        parts = [
            "Available built-in tools:\n"
            + json.dumps(
                builtin_manifest,
                ensure_ascii=False,
                indent=2,
            ),
            self.builtins.format_tool_prompts(
                exclude=set(self.excluded) | denied_builtins,
            ),
        ]
        skills = [
            {"name": row["name"], "description": row["description"]}
            for row in self.skills
            if self._allowed(f"skill:{row['name']}")
        ]
        if skills:
            parts.append(
                "Enabled user skills (search/load instructions only when useful):\n"
                + json.dumps(skills, ensure_ascii=False, indent=2)
            )
        mcp_tools = [
            {"name": tool.name, "description": tool.description}
            for tool in self.mcp_tools
            if self._allowed(tool.name, server_id=tool.server_id)
        ]
        if mcp_tools:
            parts.append(
                "Deferred user MCP tools (call tool_search before use):\n"
                + json.dumps(mcp_tools, ensure_ascii=False, indent=2)
            )
        return "\n\n".join(part for part in parts if part)

    def __contains__(self, name: str) -> bool:
        if name in {"skill_search", "skill_load"} and self.skills:
            return self._allowed(name)
        if name == "tool_search" and self.mcp_tools:
            return self._allowed(name)
        tool = self.loaded.mcp.get(name)
        if tool is not None:
            return self._allowed(name, server_id=tool.server_id)
        return (
            name not in self.excluded and name in self.builtins and self._allowed(name)
        )

    async def dispatch(self, name: str, raw_args: dict, ctx: AgentToolContext) -> dict:
        if name in {"skill_search", "skill_load", "tool_search"} and not self._allowed(
            name
        ):
            return {"error": "permission_denied", "capability": name}
        if name == "skill_search" and self.skills:
            args = _SearchArgs.model_validate(raw_args)
            matches = [
                row
                for row in skill_service.search(list(self.skills), args.query)
                if self._allowed(f"skill:{row['name']}")
            ]
            await self._record_discovered([row["name"] for row in matches])
            return {
                "skills": [
                    {"name": row["name"], "description": row["description"]}
                    for row in matches
                ]
            }
        if name == "skill_load" and self.skills:
            args = _LoadSkillArgs.model_validate(raw_args)
            if not self._allowed(f"skill:{args.name}"):
                return {
                    "error": "permission_denied",
                    "capability": f"skill:{args.name}",
                }
            row = await self._load_skill(args.name)
            if row is None:
                return {"error": "skill_not_found", "name": args.name}
            if row.get("error"):
                return row
            await self._record_discovered([row["name"]])
            return {
                "name": row["name"],
                "description": row["description"],
                "instructions": row["content"],
            }
        if name == "tool_search" and self.mcp_tools:
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
        tool = self.loaded.mcp.get(name)
        if tool is not None:
            if not self._allowed(name, server_id=tool.server_id):
                return {"error": "permission_denied", "capability": name}
            try:
                validate_json(instance=raw_args, schema=tool.input_schema)
            except JSONSchemaValidationError as exc:
                return {"error": "tool_args_validation_failed", "detail": exc.message}
            return await manager.call_tool(
                self.mcp_configs[tool.server_id], tool, raw_args
            )
        if not self._allowed(name):
            return {"error": "permission_denied", "capability": name}
        return await self.builtins.dispatch(name, raw_args, ctx)

    def _search_mcp(self, query: str) -> list[MCPToolDescriptor]:
        needle = query.casefold().strip()
        available = [
            tool
            for tool in self.mcp_tools
            if self._allowed(tool.name, server_id=tool.server_id)
        ]
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
        usage = {
            item.get("tool_name"): index
            for index, item in enumerate(reversed(self.tool_history))
        }
        matches.sort(key=lambda tool: usage.get(tool.name, len(usage)))
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

    async def _record_discovered(self, names: list[str]) -> None:
        if not names or not self.session_id or not self.user_pk:
            return

        def save() -> None:
            db = SessionLocal()
            try:
                row = conversation_capability_service.get_or_create(
                    db,
                    self.session_id,
                    self.user_pk,
                )
                conversation_capability_service.record_discovered_skills(db, row, names)
            finally:
                db.close()

        await asyncio.to_thread(save)

    async def _persist_snapshot(self) -> None:
        if not self.turn_id:
            return
        snapshot = {
            "builtins": [
                name
                for name in self.builtins.tool_names
                if name not in self.excluded and self._allowed(name)
            ],
            "skills": [
                {"id": row["id"], "name": row["name"], "revision": row["updated_at"]}
                for row in self.skills
            ],
            "mcp_servers": [
                {"id": config.id, "name": config.name, "revision": config.revision}
                for config in self.mcp_configs.values()
            ],
            "mcp_tools": [tool.name for tool in self.mcp_tools],
            "permissions": dict(self.permissions),
            "excluded": sorted(self.excluded),
        }

        def save() -> None:
            db = SessionLocal()
            try:
                row = db.get(ConversationTurn, self.turn_id)
                if row is not None and not row.capability_snapshot_json:
                    row.capability_snapshot_json = snapshot
                    db.commit()
            finally:
                db.close()

        await asyncio.to_thread(save)

    async def _persist_loaded_schemas(self) -> None:
        if not self.turn_id:
            return
        schemas = [self._mcp_schema(tool) for tool in self.loaded.mcp.values()]

        def save() -> None:
            db = SessionLocal()
            try:
                row = db.get(ConversationTurn, self.turn_id)
                if row is not None:
                    row.loaded_schemas_json = schemas
                    db.commit()
            finally:
                db.close()

        await asyncio.to_thread(save)
