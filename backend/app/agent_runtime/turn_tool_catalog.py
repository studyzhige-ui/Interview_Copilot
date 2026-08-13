from __future__ import annotations

import asyncio
import json
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from app.agent_runtime.mcp import MCPToolDescriptor, manager
from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    ToolDispatchPlan,
    ToolRegistryView,
    _pydantic_to_openai_schema,
    registry,
)
from app.core.config import settings
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.conversation_turn import ConversationTurn
from app.services.capabilities import (
    mcp_server_service,
    skill_service,
)


_CLOUD_AUTOMATION_INTERNAL_TOOLS = frozenset({"review_gmail_observation"})


class _SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class _LoadSkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class _LoadSkillResourceArgs(BaseModel):
    skill_name: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=255)


def _typed_virtual_plan(
    name: str,
    raw_args: dict[str, Any],
    model: type[BaseModel],
) -> ToolDispatchPlan:
    encoded = json.dumps(raw_args, ensure_ascii=False, default=str)
    if len(encoded) > settings.AGENT_MAX_TOOL_ARG_CHARS:
        return ToolDispatchPlan(
            tool_name=name,
            arguments=dict(raw_args),
            effect=ToolEffect.READ,
            handler_exists=True,
            concurrency_safe=False,
            error={"error": "tool_args_too_large", "tool_name": name},
        )
    try:
        arguments = model.model_validate(raw_args).model_dump(mode="json")
    except Exception:  # Pydantic's structured detail stays inside the Tool contract
        return ToolDispatchPlan(
            tool_name=name,
            arguments=dict(raw_args),
            effect=ToolEffect.READ,
            handler_exists=True,
            concurrency_safe=False,
            error={"error": "tool_args_validation_failed", "tool_name": name},
        )
    return ToolDispatchPlan(
        tool_name=name,
        arguments=arguments,
        effect=ToolEffect.READ,
        handler_exists=True,
        concurrency_safe=False,
        handler_identity=(
            "app.agent_runtime.turn_tool_catalog.TurnToolCatalog.dispatch"
        ),
    )


def _validate_mcp_arguments(
    tool: MCPToolDescriptor,
    raw_args: dict[str, Any],
) -> dict[str, Any] | None:
    encoded = json.dumps(raw_args, ensure_ascii=False, default=str)
    if len(encoded) > settings.AGENT_MAX_TOOL_ARG_CHARS:
        return {"error": "tool_args_too_large", "tool_name": tool.name}
    try:
        Draft202012Validator.check_schema(tool.input_schema)
        errors = sorted(
            Draft202012Validator(tool.input_schema).iter_errors(raw_args),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
    except Exception:  # Invalid remote schema is not executable.
        return {"error": "tool_schema_invalid", "tool_name": tool.name}
    if errors:
        return {
            "error": "tool_args_validation_failed",
            "tool_name": tool.name,
            "invalid_paths": [
                ".".join(str(item) for item in error.absolute_path) or "$"
                for error in errors[:10]
            ],
        }
    return None


def cloud_sustainable_read_tool_names() -> frozenset[str]:
    """Concrete built-ins eligible for unattended cloud execution now."""

    snapshot = registry.snapshot()
    return frozenset(
        name
        for name in snapshot.tool_names
        if snapshot.effect_for(name) is ToolEffect.READ
    )


def cloud_sustainable_automation_tool_names() -> frozenset[str]:
    """Exact built-ins allowed in unattended PersistentTask definitions.

    Most are reads.  The sole write exception is the Gmail Observation review
    command: it is task-scoped, reversible through append-only correction, and
    independently revalidates source/Turn identity before any domain change.
    """

    snapshot = registry.snapshot()
    return cloud_sustainable_read_tool_names().union(
        name
        for name in _CLOUD_AUTOMATION_INTERNAL_TOOLS
        if name in snapshot.entries
        and snapshot.effect_for(name) is ToolEffect.INTERNAL_WRITE
    )


@dataclass
class _LoadedState:
    mcp: dict[str, MCPToolDescriptor] = field(default_factory=dict)
    skills: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    mcp_discovery_errors: Mapping[int, str] = field(default_factory=dict)
    runtime_profile: str = "career"
    loaded: _LoadedState = field(default_factory=_LoadedState, compare=False)
    activation_errors: tuple[str, ...] = ()

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
        runtime_profile: str = "career",
        pinned_skill_refs: list[dict[str, Any]] | None = None,
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
                loaded_mcp_names: set[str] = set()
                if turn_id:
                    turn = db.get(ConversationTurn, turn_id)
                    for schema in (
                        turn.loaded_tool_schemas_json if turn is not None else []
                    ) or []:
                        if not isinstance(schema, dict):
                            continue
                        function = schema.get("function")
                        name = (
                            function.get("name") if isinstance(function, dict) else None
                        )
                        if isinstance(name, str) and name:
                            loaded_mcp_names.add(name)
                activated, activation_errors = (
                    skill_service.load_activated_skills_for_turn(
                        db,
                        turn_id=turn_id,
                        user_pk=user_pk,
                        pinned_refs=pinned_skill_refs,
                    )
                )
                db.commit()
                if not include_deferred:
                    return (
                        user_pk,
                        [],
                        [],
                        activated,
                        activation_errors,
                        set(),
                    )
                return (
                    user_pk,
                    skill_service.list_skills(
                        db,
                        user_pk,
                        enabled_only=True,
                        include_content=False,
                    ),
                    mcp_server_service.enabled_configs(db, user_pk),
                    activated,
                    activation_errors,
                    loaded_mcp_names,
                )
            finally:
                db.close()

        loaded = await asyncio.to_thread(load)
        if loaded is None:
            user_pk, skills, configs, activated, activation_errors, loaded_mcp_names = (
                0,
                [],
                [],
                [],
                [],
                set(),
            )
        else:
            (
                user_pk,
                skills,
                configs,
                activated,
                activation_errors,
                loaded_mcp_names,
            ) = loaded
        tools, failures = (
            await manager.discover(configs) if include_deferred else ([], [])
        )

        effective_exclude = set(exclude or set())
        if builtin_allowlist is not None:
            effective_exclude.update(set(registry.tool_names) - set(builtin_allowlist))

        builtins = registry.snapshot(exclude=effective_exclude, user_id=user_id)
        available_tools = set(builtins.tool_names)
        visible_skills = [
            dict(row)
            for row in skills
            if (
                not row.get("applicable_profiles")
                or runtime_profile in set(row.get("applicable_profiles") or [])
            )
            and set(row.get("required_tools") or []).issubset(available_tools)
        ]
        valid_activated: list[dict[str, Any]] = []
        for item in activated:
            profiles = set(item.get("applicable_profiles") or [])
            missing = set(item.get("required_tools") or []) - available_tools
            if profiles and runtime_profile not in profiles:
                activation_errors.append(f"skill_profile_mismatch:{item['name']}")
            elif missing:
                activation_errors.append(
                    f"skill_required_tool_unavailable:{item['name']}:{','.join(sorted(missing))}"
                )
            else:
                valid_activated.append(item)
        loaded_state = _LoadedState(
            mcp={tool.name: tool for tool in tools if tool.name in loaded_mcp_names},
            skills={str(item["name"]): dict(item) for item in valid_activated},
        )
        catalog = cls(
            builtins=builtins,
            excluded=frozenset(effective_exclude),
            user_id=user_id,
            user_pk=user_pk,
            session_id=session_id,
            turn_id=turn_id,
            runtime_profile=runtime_profile,
            skills=tuple(
                sorted(
                    visible_skills,
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
            mcp_discovery_errors=MappingProxyType(dict(failures)),
            loaded=loaded_state,
            activation_errors=tuple(activation_errors),
        )
        await catalog._persist_snapshot()
        return catalog

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        allowed = self.effective_allowed_tools()
        schemas = [
            schema
            for schema in self.builtins.get_openai_schemas()
            if allowed is None or schema["function"]["name"] in allowed
        ]
        if self.skills:
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_search",
                    "Search the current user's enabled skills by purpose.",
                    _SearchArgs,
                )
            )
        if self.loaded.skills:
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_resource_load",
                    "Load one explicitly referenced resource from an activated skill.",
                    _LoadSkillResourceArgs,
                )
            )
            schemas.append(
                _pydantic_to_openai_schema(
                    "skill_load",
                    "Load the full instructions for one enabled skill.",
                    _LoadSkillArgs,
                )
            )
        if self.mcp_configs:
            schemas.append(
                _pydantic_to_openai_schema(
                    "tool_search",
                    "Load matching deferred MCP tool schemas before calling them.",
                    _SearchArgs,
                )
            )
        schemas.extend(self._mcp_schema(tool) for tool in self.loaded.mcp.values())
        return sorted(schemas, key=lambda schema: schema["function"]["name"])

    def effective_allowed_tools(self) -> frozenset[str] | None:
        restrictions = [
            set(item.get("allowed_tools") or [])
            for item in self.loaded.skills.values()
            if item.get("allowed_tools")
        ]
        if not restrictions:
            return None
        allowed = restrictions[0]
        for restriction in restrictions[1:]:
            allowed &= restriction
        return frozenset(allowed)

    def render_activated_skills(self) -> str:
        if not self.loaded.skills:
            return ""
        sections = []
        for name, item in sorted(self.loaded.skills.items()):
            sections.append(
                f"[Activated Skill: {name}; source={item['source']}; "
                f"revision={item['revision']}]\n{item['content']}"
            )
        return "\n\n".join(sections)

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
        if mcp_tools:
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
        if name == "skill_resource_load" and self.loaded.skills:
            return True
        if name == "tool_search" and self.mcp_configs:
            return True
        if name in self.loaded.mcp:
            return True
        allowed = self.effective_allowed_tools()
        return (
            name not in self.excluded
            and name in self.builtins
            and (allowed is None or name in allowed)
        )

    def is_concurrency_safe(self, name: str) -> bool:
        """Return true only for an explicitly safe built-in tool.

        Skill discovery and MCP tools have unknown side effects, so both remain
        serial until concrete execution policy supplies stronger annotations.
        """
        return (
            name in self
            and name not in {"skill_search", "skill_load", "skill_resource_load"}
            and self.builtins.is_concurrency_safe(name)
        )

    def effect_for(self, name: str) -> ToolEffect:
        if name in {"skill_search", "skill_load", "skill_resource_load", "tool_search"}:
            return ToolEffect.READ
        if name in self.loaded.mcp or any(
            descriptor.name == name for descriptor in self.mcp_tools
        ):
            return ToolEffect.UNKNOWN
        if name not in self:
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
        if name in {"skill_search", "skill_load", "skill_resource_load", "tool_search"}:
            return False, False
        if name in self.loaded.mcp or any(
            descriptor.name == name for descriptor in self.mcp_tools
        ):
            return False, False
        if name not in self:
            return False, False
        return self.builtins.policy_traits(name, arguments, ctx, current_task)

    async def plan_call(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: AgentToolContext,
    ) -> ToolDispatchPlan:
        """Build one typed concrete plan without starting its handler."""

        virtual_models: dict[str, type[BaseModel]] = {}
        if self.skills:
            virtual_models.update(
                {"skill_search": _SearchArgs, "skill_load": _LoadSkillArgs}
            )
        if self.loaded.skills:
            virtual_models["skill_resource_load"] = _LoadSkillResourceArgs
        if self.mcp_configs:
            virtual_models["tool_search"] = _SearchArgs
        model = virtual_models.get(name)
        if model is not None:
            plan = _typed_virtual_plan(name, raw_args, model)
            if name == "tool_search" and plan.error is None and not self.mcp_tools:
                return replace(
                    plan,
                    connection_ready=False,
                    concurrency_safe=False,
                )
            return plan

        tool = self._mcp_descriptor(name)
        if tool is not None:
            error = _validate_mcp_arguments(tool, raw_args)
            config = await self._current_mcp_config(tool)
            return ToolDispatchPlan(
                tool_name=name,
                arguments=dict(raw_args),
                effect=ToolEffect.UNKNOWN,
                handler_exists=True,
                # Unknown-effect MCP calls are always an exclusive batch.
                concurrency_safe=False,
                connection_ready=config is not None,
                resource_identities=frozenset({f"mcp-server:{tool.server_id}"}),
                handler_identity=("app.agent_runtime.mcp.manager.MCPManager.call_tool"),
                provider_identity=f"mcp:{tool.server_name}"[:255],
                connection_identity=(
                    f"mcp-server:{config.id}:revision:{config.revision}"[:255]
                    if config is not None
                    else None
                ),
                error=error,
            )

        if name not in self:
            return ToolDispatchPlan(
                tool_name=name,
                arguments=dict(raw_args),
                effect=ToolEffect.UNKNOWN,
                handler_exists=False,
                concurrency_safe=False,
                error={"error": "unknown_tool", "tool_name": name},
            )
        return await self.builtins.plan_call(name, raw_args, ctx)

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
                "source": row["source"],
                "revision": row["revision"],
                "resources": row.get("resources", []),
                "allowed_tools": row.get("allowed_tools", []),
            }
        if name == "skill_resource_load" and self.loaded.skills:
            args = _LoadSkillResourceArgs.model_validate(raw_args)
            return await self._load_skill_resource(args.skill_name, args.path)
        if name == "tool_search" and self.mcp_configs:
            if not self.mcp_tools:
                return {
                    "error": "connection_required",
                    "interaction_type": "connection",
                    "provider": "mcp",
                }
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
        tool = self._mcp_descriptor(name)
        if tool is not None:
            config = await self._current_mcp_config(tool)
            if config is None:
                return {
                    "error": "connection_required",
                    "interaction_type": "connection",
                    "provider": "mcp",
                    "tool_name": name,
                }
            return await manager.call_tool(config, tool, raw_args)
        if name not in self:
            return {"error": "unknown_tool", "tool_name": name}
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

    def _mcp_descriptor(self, name: str) -> MCPToolDescriptor | None:
        return self.loaded.mcp.get(name)

    async def _current_mcp_config(
        self,
        tool: MCPToolDescriptor,
    ) -> mcp_server_service.MCPServerConfig | None:
        """Re-read ownership/enabled state and revision at concrete-call time."""

        frozen = self.mcp_configs.get(tool.server_id)
        if frozen is None:
            return None

        def load() -> mcp_server_service.MCPServerConfig | None:
            db = SessionLocal()
            try:
                configs = mcp_server_service.enabled_configs(db, self.user_pk)
                current = next(
                    (config for config in configs if config.id == tool.server_id),
                    None,
                )
                if (
                    current is None
                    or current.name != frozen.name
                    or current.revision != frozen.revision
                ):
                    return None
                return current
            except Exception:  # noqa: BLE001 - unavailable secret/transport is closed
                return None
            finally:
                db.close()

        return await asyncio.to_thread(load)

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
                if int(row.revision or 1) != int(
                    snapshot.get("revision") or 0
                ) or row.content_hash != snapshot.get("content_hash"):
                    return {
                        "error": "skill_revision_changed",
                        "name": name,
                    }
                skill_service.activate_skill_for_turn(
                    db,
                    turn_id=self.turn_id,
                    user_pk=self.user_pk,
                    skill=row,
                )
                payload = skill_service.skill_payload(row)
                db.commit()
                return payload
            finally:
                db.close()

        result = await asyncio.to_thread(load)
        if result is not None and not result.get("error"):
            self.loaded.skills[str(result["name"])] = dict(result)
        return result

    async def _load_skill_resource(self, skill_name: str, path: str) -> dict:
        active = self.loaded.skills.get(skill_name)
        if active is None:
            return {"error": "skill_not_activated", "name": skill_name}

        def load() -> dict:
            db = SessionLocal()
            try:
                row = skill_service.get_skill(db, self.user_pk, int(active["id"]))
                if (
                    row is None
                    or not row.enabled
                    or int(row.revision or 1) != int(active["revision"])
                    or row.content_hash != active["content_hash"]
                ):
                    return {"error": "skill_revision_changed", "name": skill_name}
                resource = skill_service.load_resource(
                    db,
                    user_pk=self.user_pk,
                    skill_id=row.id,
                    path=path,
                )
                if resource is None:
                    return {
                        "error": "skill_resource_not_found",
                        "name": skill_name,
                        "path": path,
                    }
                return {
                    "skill_name": skill_name,
                    "path": resource.path,
                    "kind": resource.kind,
                    "content_hash": resource.content_hash,
                    "content": resource.content,
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
                        self.mcp_tools,
                        key=lambda item: (item.name, item.server_id),
                    )
                ],
            },
            "skills": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "source": row["source"],
                    "revision": row["revision"],
                    "content_hash": row["content_hash"],
                }
                for row in sorted(self.skills, key=lambda item: item["name"])
            ],
            "mcp_servers": [
                {"id": config.id, "name": config.name, "revision": config.revision}
                for config in sorted(
                    self.mcp_configs.values(),
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

    async def ensure_active_skill_bindings(self) -> None:
        """Bind already activated Skills if an AgentTask was created later."""

        if not self.turn_id or not self.loaded.skills:
            return

        def bind() -> None:
            db = SessionLocal()
            try:
                for active in self.loaded.skills.values():
                    row = skill_service.get_skill(db, self.user_pk, int(active["id"]))
                    if row is None:
                        raise ValueError("skill_unavailable_for_active_task")
                    skill_service.bind_skill_to_agent_task(
                        db,
                        turn_id=self.turn_id,
                        user_pk=self.user_pk,
                        skill=row,
                    )
                db.commit()
            finally:
                db.close()

        await asyncio.to_thread(bind)

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
