"""Provider-neutral streaming request and native vendor adapters.

Prompt caching is a transport optimization here, never a Context Source.  A
request is semantically complete before an adapter sees it: concrete tools,
system instructions, and chronological messages.  The Anthropic adapter maps
that request to the native Messages API and applies explicit cache breakpoints;
OpenAI-compatible providers receive the same complete request without those
Anthropic-only fields.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.core.config import settings
from app.core.model_catalog import ModelProfile


@dataclass(frozen=True)
class ProviderToolCallDelta:
    """One provider-neutral incremental tool call fragment."""

    index: int
    call_id: str = ""
    name: str = ""
    arguments_delta: str = ""


@dataclass(frozen=True)
class ProviderUsage:
    """Usage delta reported by one stream event.

    ``prompt_tokens`` is the logical input size used for context pressure.  For
    Anthropic this is uncached input + cache reads + cache creation because the
    native ``input_tokens`` field excludes both cache buckets.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True)
class ProviderStreamEvent:
    """Normalized streaming event consumed by both Chat and Agent."""

    text_delta: str = ""
    reasoning_delta: str = ""
    tool_call_deltas: tuple[ProviderToolCallDelta, ...] = ()
    usage: ProviderUsage | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class ProviderRequest:
    """The three independent provider request partitions plus generation knobs."""

    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 4_096
    temperature: float = 0.2


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied = copy.deepcopy(tools)
    return sorted(
        copied,
        key=lambda schema: str((schema.get("function") or {}).get("name") or ""),
    )


def build_provider_request(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
) -> ProviderRequest:
    """Split leading system messages and freeze deterministic concrete tools.

    Loop-local code may retain the system partition as leading messages for
    compaction.  This is the sole final split before any provider call.
    """

    system_parts: list[str] = []
    first_data_index = 0
    for first_data_index, message in enumerate(messages):
        if message.get("role") != "system":
            break
        content = str(message.get("content") or "").strip()
        if content:
            system_parts.append(content)
    else:
        first_data_index = len(messages)

    if (
        first_data_index < len(messages)
        and messages[first_data_index].get("role") == "system"
    ):
        first_data_index += 1

    chronological = copy.deepcopy(messages[first_data_index:])
    if any(message.get("role") == "system" for message in chronological):
        raise ValueError("system messages must form one leading provider partition")
    if not chronological:
        raise ValueError("provider request requires at least one chronological message")

    return ProviderRequest(
        system="\n\n".join(system_parts),
        messages=chronological,
        tools=_canonical_tools(list(tools or [])),
        max_tokens=max(1, int(max_tokens)),
        temperature=float(temperature),
    )


def _openai_payload(profile: ModelProfile, request: ProviderRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": profile.model,
        "messages": copy.deepcopy(request.messages),
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if request.system:
        payload["messages"] = [
            {"role": "system", "content": request.system},
            *payload["messages"],
        ]
    if request.tools:
        payload["tools"] = copy.deepcopy(request.tools)
        payload["tool_choice"] = "auto"
    return payload


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate canonical chronological messages to native Messages blocks."""

    translated: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            native_role = "user"
            blocks: list[dict[str, Any]] = []
            content = str(message.get("content") or "")
            if content:
                blocks.append({"type": "text", "text": content})
        elif role == "assistant":
            native_role = "assistant"
            blocks = []
            content = str(message.get("content") or "")
            if content:
                blocks.append({"type": "text", "text": content})
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(tool_call.get("id") or ""),
                        "name": str(function.get("name") or ""),
                        "input": _parse_arguments(function.get("arguments")),
                    }
                )
        elif role == "tool":
            native_role = "user"
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or ""),
                    "content": str(message.get("content") or ""),
                }
            ]
        else:
            raise ValueError(f"unsupported chronological role: {role!r}")

        if not blocks:
            # An empty canonical message has no model-visible semantics.  Do
            # not manufacture an empty text block: native Messages rejects
            # cache markers on empty text, and a transport placeholder would
            # become content that Context Assembly never produced.
            continue

        # Consecutive canonical tool results are one native user turn.  More
        # generally, merging adjacent equal roles mirrors the Messages API's
        # documented normalization and keeps the wire bytes deterministic.
        if translated and translated[-1]["role"] == native_role:
            translated[-1]["content"].extend(blocks)
        else:
            translated.append({"role": native_role, "content": blocks})
    if not translated:
        raise ValueError("Anthropic request requires at least one semantic message")
    return translated


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    native: list[dict[str, Any]] = []
    for schema in tools:
        function = schema.get("function") or {}
        native.append(
            {
                "name": str(function.get("name") or ""),
                "description": str(function.get("description") or ""),
                "input_schema": copy.deepcopy(function.get("parameters") or {}),
            }
        )
    return native


def build_anthropic_payload(request: ProviderRequest) -> dict[str, Any]:
    """Build native Anthropic wire data with explicit prefix breakpoints."""

    messages = _anthropic_messages(request.messages)
    tools = _anthropic_tools(request.tools)
    system: list[dict[str, Any]] = []
    if request.system:
        system.append({"type": "text", "text": request.system})

    cache_enabled = bool(settings.ANTHROPIC_PROMPT_CACHE_ENABLED)
    if cache_enabled:
        cache_control = {
            "type": "ephemeral",
            "ttl": settings.ANTHROPIC_PROMPT_CACHE_TTL,
        }
        # Anthropic evaluates the physical prefix as tools -> system ->
        # messages, but its cache is shared at workspace scope and exposes no
        # per-product-user namespace.  Only the non-private deterministic
        # tools/system prefix is therefore cacheable in a shared deployment.
        # User History, retrieved data, guidance and the current input remain
        # semantically complete messages without a cache marker.
        if tools:
            tools[-1]["cache_control"] = copy.deepcopy(cache_control)
        if system:
            system[-1]["cache_control"] = copy.deepcopy(cache_control)

    payload: dict[str, Any] = {
        "messages": messages,
        "max_tokens": request.max_tokens,
        "stream": True,
    }
    # Current Claude models deprecate temperature and models released after
    # Opus 4.6 reject non-default values.  The catalog does not expose a
    # per-model temperature capability, so omission is the only portable native
    # request.  This is a provider capability mapping, not Context semantics.
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = {"type": "auto"}
    return payload


def normalize_openai_chunk(chunk: Any) -> ProviderStreamEvent:
    """Normalize one compatibility-stream chunk (also a focused-test seam)."""

    usage = _value(chunk, "usage")
    normalized_usage: ProviderUsage | None = None
    if usage is not None:
        details = _value(usage, "prompt_tokens_details")
        normalized_usage = ProviderUsage(
            prompt_tokens=int(_value(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(_value(usage, "completion_tokens", 0) or 0),
            cache_read_tokens=int(
                _value(details, "cached_tokens", 0)
                or _value(usage, "cache_read_input_tokens", 0)
                or _value(usage, "cache_read_tokens", 0)
                or 0
            ),
            cache_creation_tokens=int(
                _value(usage, "cache_creation_input_tokens", 0)
                or _value(usage, "cache_creation_tokens", 0)
                or 0
            ),
        )

    choices = _value(chunk, "choices", []) or []
    if not choices:
        return ProviderStreamEvent(usage=normalized_usage)

    choice = choices[0]
    delta = _value(choice, "delta")
    tool_deltas: list[ProviderToolCallDelta] = []
    for tool_call in _value(delta, "tool_calls", []) or []:
        function = _value(tool_call, "function")
        tool_deltas.append(
            ProviderToolCallDelta(
                index=int(_value(tool_call, "index", 0) or 0),
                call_id=str(_value(tool_call, "id", "") or ""),
                name=str(_value(function, "name", "") or ""),
                arguments_delta=str(_value(function, "arguments", "") or ""),
            )
        )
    return ProviderStreamEvent(
        text_delta=str(_value(delta, "content", "") or ""),
        reasoning_delta=str(_value(delta, "reasoning_content", "") or ""),
        tool_call_deltas=tuple(tool_deltas),
        usage=normalized_usage,
        stop_reason=_value(choice, "finish_reason"),
    )


async def _normalize_openai_stream(stream: Any) -> AsyncIterator[ProviderStreamEvent]:
    async for chunk in stream:
        yield normalize_openai_chunk(chunk)


async def _normalize_anthropic_stream(
    stream: Any,
) -> AsyncIterator[ProviderStreamEvent]:
    async for event in stream:
        event_type = str(_value(event, "type", "") or "")
        if event_type == "message_start":
            usage = _value(_value(event, "message"), "usage")
            if usage is not None:
                cache_read = int(_value(usage, "cache_read_input_tokens", 0) or 0)
                cache_creation = int(
                    _value(usage, "cache_creation_input_tokens", 0) or 0
                )
                uncached = int(_value(usage, "input_tokens", 0) or 0)
                yield ProviderStreamEvent(
                    usage=ProviderUsage(
                        prompt_tokens=uncached + cache_read + cache_creation,
                        cache_read_tokens=cache_read,
                        cache_creation_tokens=cache_creation,
                    )
                )
            continue

        if event_type == "content_block_start":
            block = _value(event, "content_block")
            if _value(block, "type") == "tool_use":
                initial_input = _value(block, "input", {}) or {}
                yield ProviderStreamEvent(
                    tool_call_deltas=(
                        ProviderToolCallDelta(
                            index=int(_value(event, "index", 0) or 0),
                            call_id=str(_value(block, "id", "") or ""),
                            name=str(_value(block, "name", "") or ""),
                            arguments_delta=(
                                json.dumps(initial_input, ensure_ascii=False)
                                if initial_input
                                else ""
                            ),
                        ),
                    )
                )
            continue

        if event_type == "content_block_delta":
            delta = _value(event, "delta")
            delta_type = _value(delta, "type")
            if delta_type == "text_delta":
                yield ProviderStreamEvent(
                    text_delta=str(_value(delta, "text", "") or "")
                )
            elif delta_type == "input_json_delta":
                yield ProviderStreamEvent(
                    tool_call_deltas=(
                        ProviderToolCallDelta(
                            index=int(_value(event, "index", 0) or 0),
                            arguments_delta=str(
                                _value(delta, "partial_json", "") or ""
                            ),
                        ),
                    )
                )
            elif delta_type == "thinking_delta":
                yield ProviderStreamEvent(
                    reasoning_delta=str(_value(delta, "thinking", "") or "")
                )
            continue

        if event_type == "message_delta":
            usage = _value(event, "usage")
            output_tokens = int(_value(usage, "output_tokens", 0) or 0)
            yield ProviderStreamEvent(
                usage=(
                    ProviderUsage(completion_tokens=output_tokens)
                    if output_tokens
                    else None
                ),
                stop_reason=_value(_value(event, "delta"), "stop_reason"),
            )


class ModelProviderAdapter:
    """Native transport selected from the immutable model profile."""

    def __init__(self, *, client: Any, profile: ModelProfile) -> None:
        self.client = client
        self.profile = profile

    @property
    def prompt_cache_supported(self) -> bool:
        return str(getattr(self.profile, "provider", "") or "") == "anthropic"

    @property
    def prompt_cache_enabled(self) -> bool:
        return self.prompt_cache_supported and bool(
            settings.ANTHROPIC_PROMPT_CACHE_ENABLED
        )

    async def start_stream(
        self,
        request: ProviderRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        if str(getattr(self.profile, "provider", "") or "") == "anthropic":
            payload = build_anthropic_payload(request)
            stream = await self.client.messages.create(
                model=self.profile.model,
                **payload,
            )
            return _normalize_anthropic_stream(stream)

        payload = _openai_payload(self.profile, request)
        stream = await self.client.chat.completions.create(**payload)
        return _normalize_openai_stream(stream)


__all__ = [
    "ModelProviderAdapter",
    "ProviderRequest",
    "ProviderStreamEvent",
    "ProviderToolCallDelta",
    "ProviderUsage",
    "build_anthropic_payload",
    "build_provider_request",
    "normalize_openai_chunk",
]
