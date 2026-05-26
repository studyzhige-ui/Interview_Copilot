"""Vendor adapter base — declarative spec + shared fetch logic (P7-A).

Each vendor module under ``vendors/`` declares a ``VendorAdapterSpec``
describing the URL path, auth style, response shape, and an optional
``chat_filter`` predicate. The shared ``fetch_one_vendor`` here handles:

  * URL construction + auth header / query-param injection
  * HTTP GET with 1 retry on transient failure (same 3-layer protection
    pattern as the old LiteLLM loader)
  * JSON parse + per-row extraction into ``ModelEntry``
  * Per-row chat-only filtering (most vendors return embedding /
    image / audio entries we need to drop)
  * Display-name fallback + id-prefix stripping (Gemini's ``models/``
    prefix etc.)
  * Last-known-good fallback is NOT done here — that's the pipeline's
    job; this layer just raises ``VendorFetchFailed`` on terminal
    failure so the pipeline can decide what to serve.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

import httpx

from ..base import ModelEntry

logger = logging.getLogger(__name__)


# Per-attempt HTTP timeout. 20s is generous for the small JSON
# payloads /v1/models returns (typically <100 KB).
_HTTP_TIMEOUT_S: float = 20.0
# One retry catches transient 5xx / network blip without burning
# wall-time when the upstream is genuinely down.
_HTTP_RETRIES: int = 1


class VendorFetchFailed(Exception):
    """Raised when the vendor's /v1/models call fails terminally.
    Caller (pipeline) catches this and falls back to last-known-good."""


AuthStyle = Literal["bearer", "x-api-key", "url-key"]


@dataclass(frozen=True)
class VendorAdapterSpec:
    """Declarative description of how to talk to one vendor's /v1/models.

    Most vendors fit the OpenAI-compatible shape with only minor
    deviations (path, auth header, response key); a few (Anthropic,
    Gemini) need the extras below.
    """
    # PROVIDERS dict id — joins back to provider defaults for api_base.
    provider: str

    # Path appended to ``ProviderDefaults.default_api_base``. Usually
    # ``"/models"`` or ``"/v1/models"`` or ``"/v1beta/models"``.
    models_path: str

    # How the API key reaches the vendor.
    auth_style: AuthStyle

    # Additional headers (e.g. Anthropic's ``anthropic-version``).
    # Frozen via tuple-of-tuples so the dataclass stays hashable.
    extra_headers: tuple[tuple[str, str], ...] = ()

    # Where in the JSON the model list lives.
    response_top_key: str = "data"

    # Field within each model entry that holds the API id we send back
    # in chat completion requests.
    id_field: str = "id"

    # Field holding a human-friendly display name, if the vendor
    # provides one. None → synthesise from id.
    display_name_field: str | None = None

    # Field holding a unix int timestamp (OpenAI, NVIDIA, zai).
    created_int_field: str | None = None

    # Field holding an ISO-8601 string timestamp (Anthropic).
    created_iso_field: str | None = None

    # Field for context window — Gemini uses ``inputTokenLimit``.
    context_window_field: str | None = None

    # Field for max output — Gemini uses ``outputTokenLimit``.
    max_output_field: str | None = None

    # Vendor-side id prefix to strip before storage. Gemini returns
    # ``"models/gemini-2.5-flash"``; we store ``"gemini-2.5-flash"``.
    strip_id_prefix: str | None = None

    # Optional per-vendor chat-only filter. Receives (raw_entry, bare_id);
    # return True to keep, False to drop. Used to filter out embedding /
    # image / audio / video / safety / etc. entries the vendor includes
    # in /v1/models. None = keep every row.
    chat_filter: Callable[[dict[str, Any], str], bool] | None = field(
        default=None, compare=False, hash=False,
    )

    # Default-when-vendor-doesn't-publish-it values.
    fallback_context_window: int = 128_000
    fallback_max_output: int = 4_096
    fallback_supports_function_calling: bool = True


def _headers_for(spec: VendorAdapterSpec, api_key: str) -> dict[str, str]:
    base: dict[str, str] = dict(spec.extra_headers)
    if spec.auth_style == "bearer":
        base["Authorization"] = f"Bearer {api_key}"
    elif spec.auth_style == "x-api-key":
        base["x-api-key"] = api_key
    # "url-key" → no auth header; key goes in the URL query string.
    return base


def _url_for(spec: VendorAdapterSpec, api_base: str, api_key: str) -> str:
    url = api_base.rstrip("/") + "/" + spec.models_path.lstrip("/")
    if spec.auth_style == "url-key":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"
    return url


def _coerce_timestamp(spec: VendorAdapterSpec, entry: dict[str, Any]) -> int:
    """Return the entry's creation time as a Unix int, or 0 if none."""
    if spec.created_int_field:
        v = entry.get(spec.created_int_field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            # NVIDIA NIM ships an identical sentinel (735790403 = 1993-04-26)
            # for every entry — clearly meaningless. Drop anything older
            # than 2020-01-01 (Unix 1577836800) since no real LLM existed
            # before then; we'd rather lose ordering than be misled.
            return int(v) if v > 1_577_836_800 else 0
    if spec.created_iso_field:
        v = entry.get(spec.created_iso_field)
        if isinstance(v, str) and v:
            try:
                iso = v.replace("Z", "+00:00")
                return int(datetime.fromisoformat(iso).timestamp())
            except (ValueError, TypeError):
                return 0
    return 0


def _coerce_int(val: object, default: int) -> int:
    """Float/str → int conversion that tolerates messy vendor input."""
    if isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default
    return default


def _build_entry(
    spec: VendorAdapterSpec, raw: dict[str, Any],
) -> tuple[ModelEntry, int] | None:
    """Convert one vendor row to a ModelEntry + recency key. Returns
    None if the row is unusable (missing id, fails chat filter)."""
    mid = raw.get(spec.id_field)
    if not isinstance(mid, str) or not mid.strip():
        return None
    bare = mid
    if spec.strip_id_prefix and bare.startswith(spec.strip_id_prefix):
        bare = bare[len(spec.strip_id_prefix):]
    if spec.chat_filter and not spec.chat_filter(raw, bare):
        return None

    display = mid
    if spec.display_name_field:
        v = raw.get(spec.display_name_field)
        if isinstance(v, str) and v.strip():
            display = v
        else:
            display = bare
    else:
        display = bare

    context_window = spec.fallback_context_window
    if spec.context_window_field:
        context_window = _coerce_int(
            raw.get(spec.context_window_field), spec.fallback_context_window,
        )
    max_output = spec.fallback_max_output
    if spec.max_output_field:
        max_output = _coerce_int(
            raw.get(spec.max_output_field), spec.fallback_max_output,
        )

    # Function-calling support: some vendors flag it explicitly (Gemini
    # has ``supportedGenerationMethods`` with "generateContent"; OpenAI
    # doesn't ship a flag at all). Default to the spec's fallback,
    # which is True for chat models since most modern ones support it.
    supports_fc = bool(raw.get("supports_function_calling", spec.fallback_supports_function_calling))

    supports_vision = bool(raw.get("supports_vision", False))
    # Gemini ships ``supportedGenerationMethods`` array; if it includes
    # vision-related methods we can infer support. Cheap heuristic — not
    # all vendors expose this so we just OR with whatever they do say.
    methods = raw.get("supportedGenerationMethods")
    if isinstance(methods, list):
        supports_vision = supports_vision or any("vision" in m.lower() for m in methods if isinstance(m, str))

    entry = ModelEntry(
        provider=spec.provider,
        model=bare,
        display_name=display,
        supports_function_calling=supports_fc,
        context_window=context_window,
        max_output_tokens=max_output,
        supports_vision=supports_vision,
    )
    return entry, _coerce_timestamp(spec, raw)


async def fetch_one_vendor(
    spec: VendorAdapterSpec,
    api_base: str,
    api_key: str,
    *,
    timeout: float = _HTTP_TIMEOUT_S,
    retries: int = _HTTP_RETRIES,
) -> list[ModelEntry]:
    """Fetch + parse + chat-filter + recency-sort for one vendor.

    Raises ``VendorFetchFailed`` on terminal failure (HTTP retries
    exhausted OR response is unparseable). Caller decides whether to
    serve last-known-good.

    Returned entries are sorted newest-first using whatever recency
    signal the vendor exposes (``created`` int or ``created_at`` ISO),
    falling back to reverse-alphabetical id for vendors / rows
    without a timestamp.
    """
    if not api_key:
        # Mirrors the pre-P7 contract: no key → return empty without
        # raising. The pipeline shows "未配置 API Key" in this case.
        return []

    url = _url_for(spec, api_base, api_key)
    headers = _headers_for(spec, api_key)

    last_exc: Exception | None = None
    payload: Any = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers)
                # 4xx is non-retryable (bad key / wrong URL / API gate);
                # 5xx / network errors fall through to retry.
                if 400 <= resp.status_code < 500:
                    raise VendorFetchFailed(
                        f"{spec.provider}: non-retryable HTTP {resp.status_code}",
                    )
                resp.raise_for_status()
                payload = resp.json()
                break
        except VendorFetchFailed:
            raise
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(0.5)
                logger.warning(
                    "%s: fetch attempt %d failed (%s) — retrying",
                    spec.provider, attempt + 1, exc,
                )
                continue
            logger.error(
                "%s: fetch exhausted %d attempts: %s",
                spec.provider, retries + 1, exc,
            )
            raise VendorFetchFailed(
                f"{spec.provider}: fetch failed after {retries + 1} attempts: {exc}",
            ) from exc

    if not isinstance(payload, dict):
        raise VendorFetchFailed(f"{spec.provider}: top-level JSON not a dict")
    items = payload.get(spec.response_top_key)
    if not isinstance(items, list):
        raise VendorFetchFailed(
            f"{spec.provider}: missing/non-list '{spec.response_top_key}' key",
        )

    pairs: list[tuple[ModelEntry, int]] = []
    seen_ids: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        result = _build_entry(spec, raw)
        if result is None:
            continue
        entry, ts = result
        if entry.model in seen_ids:
            # Some vendors (notably NVIDIA NIM) ship the same id twice
            # — keep the first occurrence.
            continue
        seen_ids.add(entry.model)
        pairs.append((entry, ts))

    # Sort newest-first: timestamp desc as primary, reverse-alpha by id
    # as secondary (handles vendors / rows without a timestamp). Two-
    # pass stable sort gives the right compound ordering.
    pairs.sort(key=lambda p: p[0].model, reverse=True)
    pairs.sort(key=lambda p: p[1], reverse=True)
    return [e for e, _ in pairs]


__all__ = ["VendorAdapterSpec", "VendorFetchFailed", "fetch_one_vendor"]
