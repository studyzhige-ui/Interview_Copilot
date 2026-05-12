"""Unified Tool Registry for the Agent Harness.

Design reference: Hermes Agent ``tools/registry.py`` — module-level
``registry.register()`` self-registration pattern with a singleton
``ToolRegistry``.

Key differences from the old ``tools.py``:
  - No LlamaIndex / ``FunctionTool`` dependency (schema generated from Pydantic).
  - Per-tool ``max_result_chars`` instead of a single global limit.
  - ``check_fn`` for runtime availability checks.
  - ``toolset`` grouping for scenario-based tool selection.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Context passed to every tool handler ─────────────────────────────────

@dataclass
class AgentToolContext:
    user_id: str
    session_id: str


# ── Tool Entry ───────────────────────────────────────────────────────────

@dataclass
class ToolEntry:
    """A registered tool's complete descriptor."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel, AgentToolContext], Awaitable[dict[str, Any]]]
    toolset: str = "default"
    max_result_chars: int = 8000
    check_fn: Callable[[], bool] | None = None
    emoji: str = "🔧"


# ── Schema generation (Pydantic → OpenAI function calling) ───────────────

def _pydantic_to_openai_schema(name: str, description: str, model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model to an OpenAI function-calling tool schema."""
    json_schema = model.model_json_schema()

    # Clean up Pydantic-specific keys that OpenAI strict mode rejects
    def _clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            obj.pop("title", None)
            obj.pop("description", None) if "properties" not in obj else None
            for val in obj.values():
                _clean(val)
        elif isinstance(obj, list):
            for item in obj:
                _clean(item)
        return obj

    properties = json_schema.get("properties", {})
    required = json_schema.get("required", list(properties.keys()))

    # Clean nested schemas
    cleaned_props = {}
    for prop_name, prop_schema in properties.items():
        cleaned = dict(prop_schema)
        cleaned.pop("title", None)
        cleaned_props[prop_name] = cleaned

    schema: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": cleaned_props,
                "required": required,
                "additionalProperties": False,
            },
        },
    }

    if settings.AGENT_TOOL_SCHEMA_STRICT:
        schema["function"]["strict"] = True

    return schema


# ── Registry ─────────────────────────────────────────────────────────────

class ToolRegistry:
    """Process-level tool registration centre."""

    def __init__(self) -> None:
        self._entries: dict[str, ToolEntry] = {}
        self._default_tools_loaded = False
        self._loading_default_tools = False

    def _ensure_default_tools_loaded(self) -> None:
        """Import built-in tool modules once so self-registration runs.

        Tool modules register themselves as an import side effect.  Keeping
        this lazy avoids import-order coupling: callers can safely import the
        registry directly and still see the default tool set on first use.
        """
        if self._default_tools_loaded or self._loading_default_tools:
            return

        self._loading_default_tools = True
        try:
            import app.agent_runtime.tools  # noqa: F401

            self._default_tools_loaded = True
        finally:
            self._loading_default_tools = False

    def register(self, entry: ToolEntry) -> None:
        if entry.name in self._entries:
            logger.warning("Tool %r re-registered (overwriting)", entry.name)
        self._entries[entry.name] = entry
        logger.debug("Registered tool: %s [toolset=%s]", entry.name, entry.toolset)

    def get(self, name: str) -> ToolEntry | None:
        self._ensure_default_tools_loaded()
        return self._entries.get(name)

    def available_tools(self, toolset: str = "default") -> list[ToolEntry]:
        """Return tools belonging to *toolset* (or all if ``"*"``).

        Tools whose ``check_fn`` returns ``False`` are excluded.
        """
        self._ensure_default_tools_loaded()
        entries = []
        for entry in self._entries.values():
            if toolset != "*" and entry.toolset != toolset and entry.toolset != "default":
                # Include tools from "default" toolset in all toolsets
                if toolset != "default":
                    continue
            if entry.check_fn is not None and not entry.check_fn():
                continue
            entries.append(entry)
        return entries

    def get_openai_schemas(self, toolset: str = "default") -> list[dict[str, Any]]:
        """Build OpenAI function-calling schemas for the specified toolset."""
        self._ensure_default_tools_loaded()
        schemas = []
        for entry in self._entries.values():
            if entry.check_fn is not None and not entry.check_fn():
                continue
            schemas.append(
                _pydantic_to_openai_schema(entry.name, entry.description, entry.args_model)
            )
        return schemas

    def format_manifest(self) -> str:
        """Human-readable tool manifest for the system prompt."""
        self._ensure_default_tools_loaded()
        manifest = []
        for entry in self._entries.values():
            if entry.check_fn is not None and not entry.check_fn():
                continue
            schema = _pydantic_to_openai_schema(entry.name, entry.description, entry.args_model)
            manifest.append({
                "name": entry.name,
                "description": entry.description,
                "parameters": schema["function"]["parameters"],
            })
        return json.dumps(manifest, ensure_ascii=False, indent=2)

    async def dispatch(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: AgentToolContext,
    ) -> dict[str, Any]:
        """Validate arguments and execute a tool handler.

        Returns the tool result dict.  On validation error, returns an
        error dict instead of raising.
        """
        self._ensure_default_tools_loaded()
        entry = self._entries.get(name)
        if entry is None:
            return {"error": "unknown_tool", "tool_name": name}

        # Validate args
        args_json = json.dumps(raw_args, ensure_ascii=False)
        if len(args_json) > settings.AGENT_MAX_TOOL_ARG_CHARS:
            return {"error": "tool_args_too_large", "tool_name": name}

        try:
            validated = entry.args_model.model_validate(raw_args)
        except ValidationError as exc:
            return {
                "error": "tool_args_validation_failed",
                "tool_name": name,
                "details": exc.errors(),
            }

        # Execute
        result = await entry.handler(validated, ctx)

        return result

    @property
    def tool_names(self) -> list[str]:
        self._ensure_default_tools_loaded()
        return list(self._entries.keys())

    def __contains__(self, name: str) -> bool:
        self._ensure_default_tools_loaded()
        return name in self._entries


# ── Global singleton ─────────────────────────────────────────────────────

registry = ToolRegistry()


# ── Utility functions (carried over from old tools.py) ───────────────────

def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except Exception as exc:
        raise ValueError(f"tool arguments are not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"non_serializable": str(value)}, ensure_ascii=False)
