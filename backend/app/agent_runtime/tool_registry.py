"""The single registry of concrete tools exposed to the agent.

Every registered definition owns a real typed input contract and handler.  The
registry only stores, filters and looks up definitions; it never groups tools
into business capabilities or chooses an implementation on the model's behalf.
"""

import json
import logging
from collections.abc import Collection
from dataclasses import dataclass
from inspect import isawaitable
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from pydantic import BaseModel, ValidationError

from app.core.config import settings

from .tool_policy import ToolEffect

logger = logging.getLogger(__name__)


# ── Context passed to every tool handler ─────────────────────────────────


@dataclass
class AgentToolContext:
    user_id: str
    session_id: str
    # Populated by the Turn host for runtime-scoped tools. Ordinary product
    # tools do not need these fields and remain source-compatible in tests.
    turn_id: str | None = None
    user_pk: int | None = None
    # Exact model-issued call identity for handlers that must suspend and
    # resume a typed effect on the same Tool Call (for example Client Action).
    tool_call_id: str | None = None


# ── Concrete tool definition ─────────────────────────────────────────────


@dataclass(frozen=True)
class ToolPreflightResult:
    """Call-time facts a concrete handler can determine without dispatching.

    This is not a second policy layer.  A ToolDefinition may only report real
    connection/scope/resource facts; the shared Tool Policy still owns the
    allow/ask/deny decision.
    """

    connection_ready: bool = True
    provider_scope_allows: bool = True
    hard_deny_reason: str | None = None
    resource_identities: tuple[str, ...] = ()
    provider_identity: str | None = None
    connection_identity: str | None = None


@dataclass(frozen=True)
class ToolDispatchPlan:
    """Validated, side-effect-free projection of one concrete Tool Call."""

    tool_name: str
    arguments: dict[str, Any]
    effect: ToolEffect
    handler_exists: bool
    concurrency_safe: bool
    connection_ready: bool = True
    provider_scope_allows: bool = True
    hard_deny_reason: str | None = None
    resource_identities: frozenset[str] = frozenset()
    handler_identity: str | None = None
    provider_identity: str | None = None
    connection_identity: str | None = None
    receipt_ref_resolver: Callable[[dict[str, Any]], Collection[str]] | None = None
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """A model-callable concrete tool with one real execution handler."""

    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel, AgentToolContext], Awaitable[dict[str, Any]]]
    max_result_chars: int = 8000
    emoji: str = "🔧"
    prompt: str = ""
    effect: ToolEffect = ToolEffect.UNKNOWN
    # A deterministic predicate over the current admitted task and concrete
    # arguments. It may narrow approval requirements, never widen ownership,
    # Provider scope, or domain invariants enforced by the handler.
    task_authorizer: (
        Callable[[dict[str, Any], "AgentToolContext", str], bool] | None
    ) = None
    # Client Actions may bypass a redundant generic approval only when the
    # exact action is both task-authorized and limited to reversible UI work.
    reversible: bool = False
    # True only when multiple calls can run concurrently without observable
    # ordering dependencies. Unknown and mutating tools stay serial by default.
    concurrency_safe: bool = False
    # Optional zero-dispatch check for real connection/scope readiness and
    # concrete resource identities.  It must not call the provider operation
    # or mutate product state.  Policy remains centralized in tool_policy.py.
    preflight: (
        Callable[
            [BaseModel, "AgentToolContext"],
            ToolPreflightResult | Awaitable[ToolPreflightResult],
        ]
        | None
    ) = None
    # Deterministic resource identities derived from typed arguments.  The
    # batch planner keeps intersecting identities out of the same parallel
    # batch; this refines (and never widens) ``concurrency_safe``.
    resource_resolver: (
        Callable[[BaseModel, "AgentToolContext"], Collection[str]] | None
    ) = None
    # Receipt identities are extracted only when this concrete ToolDefinition
    # declares their typed result contract. Generic result keys/text are never
    # interpreted as external proof by the runtime.
    receipt_ref_resolver: Callable[[dict[str, Any]], Collection[str]] | None = None


@dataclass(frozen=True)
class ToolRegistryView:
    """A turn-local immutable snapshot of available built-in entries."""

    entries: Mapping[str, ToolDefinition]

    def get_openai_schemas(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            _pydantic_to_openai_schema(entry.name, entry.description, entry.args_model)
            for entry in self._ordered_entries()
        ]

    def format_guidance(self, **_kwargs: Any) -> str:
        """Return optional tool-specific instructions without repeating schemas."""

        sections = [
            f"## {entry.name}\n{entry.prompt}"
            for entry in self._ordered_entries()
            if entry.prompt
        ]
        return "\n\n# Tool guidance\n\n" + "\n\n".join(sections) if sections else ""

    def _ordered_entries(self) -> list[ToolDefinition]:
        return [self.entries[name] for name in sorted(self.entries)]

    async def dispatch(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: AgentToolContext,
    ) -> dict[str, Any]:
        entry = self.entries.get(name)
        if entry is None:
            return {"error": "unknown_tool", "tool_name": name}
        return await _dispatch_entry(entry, raw_args, ctx)

    async def plan_call(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: AgentToolContext,
    ) -> ToolDispatchPlan:
        """Validate one call and collect concrete facts without dispatching."""

        entry = self.entries.get(name)
        if entry is None:
            return _missing_tool_plan(name, raw_args)
        return await _plan_entry(entry, raw_args, ctx)

    def is_concurrency_safe(self, name: str) -> bool:
        entry = self.entries.get(name)
        return bool(entry and entry.concurrency_safe)

    def effect_for(self, name: str) -> ToolEffect:
        entry = self.entries.get(name)
        return entry.effect if entry else ToolEffect.UNKNOWN

    def policy_traits(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: AgentToolContext,
        current_task: str,
    ) -> tuple[bool, bool]:
        entry = self.entries.get(name)
        if entry is None:
            return False, False
        authorized = bool(
            entry.task_authorizer
            and entry.task_authorizer(arguments, ctx, current_task)
        )
        return authorized, bool(entry.reversible)

    def __contains__(self, name: str) -> bool:
        return name in self.entries

    @property
    def tool_names(self) -> list[str]:
        return sorted(self.entries)


# ── Schema generation (Pydantic → OpenAI function calling) ───────────────


def _clean_schema(obj: Any, *, schema_node: bool = True) -> Any:
    """Recursively strip Pydantic-specific keys from a JSON Schema object.

    OpenAI strict mode rejects ``title`` on property schemas and
    ``description`` on non-root objects.  The old code only popped
    ``title`` one level deep, leaving nested Pydantic models dirty.
    """
    if isinstance(obj, dict):
        # ``title`` can also be a legitimate field name inside a properties
        # mapping. Strip metadata only from actual schema nodes, never from
        # maps whose keys are user-defined property/definition names.
        if schema_node:
            obj.pop("title", None)
            if "properties" not in obj:
                obj.pop("description", None)
        for key, val in obj.items():
            _clean_schema(
                val,
                schema_node=key
                not in {"properties", "$defs", "definitions", "patternProperties"},
            )
    elif isinstance(obj, list):
        for item in obj:
            _clean_schema(item)
    return obj


def _enforce_strict_object_contracts(obj: Any) -> None:
    """Make every object node satisfy provider strict-function rules."""

    if isinstance(obj, dict):
        properties = obj.get("properties")
        if isinstance(properties, dict):
            obj["additionalProperties"] = False
            obj["required"] = list(properties)
        for value in obj.values():
            _enforce_strict_object_contracts(value)
    elif isinstance(obj, list):
        for item in obj:
            _enforce_strict_object_contracts(item)


def _pydantic_to_openai_schema(
    name: str, description: str, model: type[BaseModel]
) -> dict[str, Any]:
    """Convert a Pydantic model to an OpenAI function-calling tool schema."""
    json_schema = model.model_json_schema()

    properties = json_schema.get("properties", {})
    required = json_schema.get("required", list(properties.keys()))

    # Recursively clean Pydantic-specific keys that OpenAI strict mode
    # rejects (title on leaf schemas, description on non-root objects).
    cleaned_props = {}
    for prop_name, prop_schema in properties.items():
        cleaned_props[prop_name] = _clean_schema(dict(prop_schema))

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": cleaned_props,
        "required": required,
        "additionalProperties": False,
    }
    # Preserve Pydantic's local definitions when nested typed models are
    # present. Dropping them leaves dangling ``#/$defs/...`` references.
    if json_schema.get("$defs"):
        parameters["$defs"] = _clean_schema(dict(json_schema["$defs"]))

    schema: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }

    if settings.AGENT_TOOL_SCHEMA_STRICT:
        _enforce_strict_object_contracts(parameters)
        schema["function"]["strict"] = True

    return schema


# ── Registry ─────────────────────────────────────────────────────────────


class ToolRegistry:
    """Process-level tool registration centre."""

    def __init__(self) -> None:
        self._entries: dict[str, ToolDefinition] = {}
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

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._entries:
            logger.warning("Tool %r re-registered (overwriting)", definition.name)
        self._entries[definition.name] = definition
        logger.debug("Registered concrete tool: %s", definition.name)

    def get(self, name: str) -> ToolDefinition | None:
        self._ensure_default_tools_loaded()
        return self._entries.get(name)

    def _iter_available(
        self,
        *,
        exclude: set[str] | None = None,
        user_id: str | None = None,
    ) -> list[ToolDefinition]:
        """Return registered definitions not removed by deterministic visibility."""
        self._ensure_default_tools_loaded()
        exclude = exclude or set()
        entries = []
        for name in sorted(self._entries):
            entry = self._entries[name]
            if entry.name in exclude:
                continue
            entries.append(entry)
        return entries

    def get_openai_schemas(
        self,
        *,
        exclude: set[str] | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build OpenAI function-calling schemas for available tools.

        ``exclude`` is reserved for deterministic product/edition visibility.
        Connection and scope are execution-time facts and therefore do not hide
        an otherwise real tool definition.
        """
        return [
            _pydantic_to_openai_schema(e.name, e.description, e.args_model)
            for e in self._iter_available(exclude=exclude, user_id=user_id)
        ]

    def format_guidance(
        self,
        *,
        exclude: set[str] | None = None,
        user_id: str | None = None,
    ) -> str:
        """Collect non-empty ``prompt`` fields into a system-prompt block.

        Returns an empty string when no tools carry prompts, so callers
        can safely append without a conditional.
        """
        sections: list[str] = []
        for entry in self._iter_available(exclude=exclude, user_id=user_id):
            if entry.prompt:
                sections.append(f"## {entry.name}\n{entry.prompt}")
        if not sections:
            return ""
        return "\n\n# Tool guidance\n\n" + "\n\n".join(sections)

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

        return await _dispatch_entry(entry, raw_args, ctx)

    async def plan_call(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: AgentToolContext,
    ) -> ToolDispatchPlan:
        self._ensure_default_tools_loaded()
        entry = self._entries.get(name)
        if entry is None:
            return _missing_tool_plan(name, raw_args)
        return await _plan_entry(entry, raw_args, ctx)

    def is_concurrency_safe(self, name: str) -> bool:
        entry = self.get(name)
        return bool(entry and entry.concurrency_safe)

    def effect_for(self, name: str) -> ToolEffect:
        entry = self.get(name)
        return entry.effect if entry else ToolEffect.UNKNOWN

    def policy_traits(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: AgentToolContext,
        current_task: str,
    ) -> tuple[bool, bool]:
        entry = self.get(name)
        if entry is None:
            return False, False
        authorized = bool(
            entry.task_authorizer
            and entry.task_authorizer(arguments, ctx, current_task)
        )
        return authorized, bool(entry.reversible)

    def snapshot(
        self,
        *,
        exclude: set[str] | None = None,
        user_id: str | None = None,
    ) -> ToolRegistryView:
        entries = {
            entry.name: entry
            for entry in self._iter_available(exclude=exclude, user_id=user_id)
        }
        return ToolRegistryView(MappingProxyType(entries))

    @property
    def tool_names(self) -> list[str]:
        self._ensure_default_tools_loaded()
        return sorted(self._entries)

    def __contains__(self, name: str) -> bool:
        self._ensure_default_tools_loaded()
        return name in self._entries


# ── Global singleton ─────────────────────────────────────────────────────

registry = ToolRegistry()


async def _dispatch_entry(
    entry: ToolDefinition,
    raw_args: dict[str, Any],
    ctx: AgentToolContext,
) -> dict[str, Any]:
    args_json = json.dumps(raw_args, ensure_ascii=False)
    if len(args_json) > settings.AGENT_MAX_TOOL_ARG_CHARS:
        return {"error": "tool_args_too_large", "tool_name": entry.name}
    try:
        validated = entry.args_model.model_validate(raw_args)
    except ValidationError as exc:
        return {
            "error": "tool_args_validation_failed",
            "tool_name": entry.name,
            "details": exc.errors(),
        }
    return await entry.handler(validated, ctx)


def _missing_tool_plan(name: str, raw_args: dict[str, Any]) -> ToolDispatchPlan:
    return ToolDispatchPlan(
        tool_name=name,
        arguments=dict(raw_args),
        effect=ToolEffect.UNKNOWN,
        handler_exists=False,
        concurrency_safe=False,
        error={"error": "unknown_tool", "tool_name": name},
    )


def _callable_identity(handler: Callable[..., Any]) -> str:
    module = str(getattr(handler, "__module__", "") or "").strip()
    qualname = str(
        getattr(handler, "__qualname__", "")
        or getattr(handler, "__name__", "")
        or "handler"
    ).strip()
    return f"{module}.{qualname}"[:255] if module else qualname[:255]


def _resource_identities(values: Collection[str]) -> frozenset[str]:
    identities: set[str] = set()
    for value in values:
        identity = str(value).strip()
        if not identity:
            continue
        if len(identity) > 512:
            raise ValueError("tool resource identity is too long")
        identities.add(identity)
        if len(identities) > 64:
            raise ValueError("too many tool resource identities")
    return frozenset(identities)


async def _plan_entry(
    entry: ToolDefinition,
    raw_args: dict[str, Any],
    ctx: AgentToolContext,
) -> ToolDispatchPlan:
    """Build the one concrete preflight projection used by the Agent loop."""

    encoded = json.dumps(raw_args, ensure_ascii=False, default=str)
    if len(encoded) > settings.AGENT_MAX_TOOL_ARG_CHARS:
        return ToolDispatchPlan(
            tool_name=entry.name,
            arguments=dict(raw_args),
            effect=entry.effect,
            handler_exists=True,
            concurrency_safe=False,
            error={"error": "tool_args_too_large", "tool_name": entry.name},
        )
    try:
        validated = entry.args_model.model_validate(raw_args)
    except ValidationError as exc:
        return ToolDispatchPlan(
            tool_name=entry.name,
            arguments=dict(raw_args),
            effect=entry.effect,
            handler_exists=True,
            concurrency_safe=False,
            error={
                "error": "tool_args_validation_failed",
                "tool_name": entry.name,
                "details": exc.errors(),
            },
        )

    arguments = validated.model_dump(mode="json")
    try:
        resources = (
            _resource_identities(entry.resource_resolver(validated, ctx))
            if entry.resource_resolver is not None
            else frozenset()
        )
        facts = ToolPreflightResult()
        if entry.preflight is not None:
            candidate = entry.preflight(validated, ctx)
            facts = await candidate if isawaitable(candidate) else candidate
            if not isinstance(facts, ToolPreflightResult):
                raise TypeError("tool preflight returned an invalid result")
        resources = resources.union(_resource_identities(facts.resource_identities))
    except Exception as exc:  # noqa: BLE001 - preflight is a trust boundary
        logger.warning("Tool preflight failed: %s (%s)", entry.name, type(exc).__name__)
        return ToolDispatchPlan(
            tool_name=entry.name,
            arguments=arguments,
            effect=entry.effect,
            handler_exists=True,
            concurrency_safe=False,
            error={"error": "tool_preflight_failed", "tool_name": entry.name},
        )

    return ToolDispatchPlan(
        tool_name=entry.name,
        arguments=arguments,
        effect=entry.effect,
        handler_exists=True,
        concurrency_safe=bool(entry.concurrency_safe),
        connection_ready=bool(facts.connection_ready),
        provider_scope_allows=bool(facts.provider_scope_allows),
        hard_deny_reason=facts.hard_deny_reason,
        resource_identities=resources,
        handler_identity=_callable_identity(entry.handler),
        provider_identity=(
            str(facts.provider_identity)[:255]
            if facts.provider_identity is not None
            else None
        ),
        connection_identity=(
            str(facts.connection_identity)[:255]
            if facts.connection_identity is not None
            else None
        ),
        receipt_ref_resolver=entry.receipt_ref_resolver,
    )


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
