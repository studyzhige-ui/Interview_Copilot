"""LiteLLM model catalog fetcher with 3-layer protection (P6-L).

Single data source for the entire model catalog. Pulls
``model_prices_and_context_window.json`` from the BerriAI/litellm
repo on GitHub, parses it, filters down to chat-mode entries we
recognise a provider for, and returns ``ModelEntry`` records grouped
by provider.

The three protection layers, in order:

  1. HTTP GET with one retry on transient failure (5xx, network blip).
  2. Parse JSON + validate schema BEFORE touching any cache write.
     Required fields per entry: ``litellm_provider`` (str), ``mode``
     (str). A LiteLLM PR that ships a malformed JSON would otherwise
     poison the cache for 24h.
  3. On any failure (HTTP exhausted retries OR validation rejected),
     return the last-known-good snapshot loaded by the caller from
     Redis / DB shadow. ``fetch_litellm_catalog`` raises
     ``LiteLLMFetchFailed`` so the caller can decide whether to fall
     back; this module is intentionally stateless about caching.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

import httpx

from .base import ModelEntry
from .providers import get_provider_defaults

logger = logging.getLogger(__name__)


# The canonical URL of LiteLLM's master model registry. Pinned to the
# main branch — LiteLLM merges new vendor models within hours-to-days
# of release. Override with the env var below to point at an internal
# mirror (air-gapped deployments, rate-limit avoidance, etc.).
LITELLM_CATALOG_URL: str = os.getenv(
    "LITELLM_CATALOG_URL",
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json",
)

# Per-attempt HTTP timeout. 20s is generous for a ~1MB GitHub-raw
# fetch (typical 200-800ms even from China via the GitHub edge).
_HTTP_TIMEOUT_S: float = 20.0

# A single retry is the right balance: transient 5xx/timeout is the
# 90%+ failure case, more than one retry just makes the cron task
# block the worker longer when the source is genuinely down.
_HTTP_RETRIES: int = 1


class LiteLLMFetchFailed(Exception):
    """Raised by ``fetch_litellm_catalog`` when even the retry
    can't return parseable, schema-valid data. Caller MUST handle
    this — usually by serving the last-known-good snapshot."""


# LiteLLM JSON entries that aren't chat-completion models. We filter
# these out of the catalog so the role-selector dropdowns don't get
# polluted with embedding / image / audio / moderation entries.
#
# LiteLLM's ``mode`` field is the authoritative signal — but a small
# number of entries lack the field altogether (older PR backlog), so
# we ALSO drop entries whose name strongly indicates non-chat.
_CHAT_MODES = {
    "chat",
    "completion",      # legacy alias some LiteLLM rows still use
    "responses",       # OpenAI Responses API
}
_NON_CHAT_NAME_HINTS = (
    "embedding", "embed-",
    "rerank", "reranker",
    "whisper", "tts-", "audio-",
    "moderation",
    "dall-e", "image-",
    "stable-diffusion",
    "midjourney",
)


def _is_chat_entry(entry: dict, model_id: str) -> bool:
    """Two-step chat-mode filter."""
    mode = entry.get("mode")
    if isinstance(mode, str) and mode in _CHAT_MODES:
        return True
    if mode is None:
        # Mode missing — fall back to the name heuristic. If the name
        # contains a non-chat hint, drop it; otherwise keep it (better
        # to ship a possibly-non-chat entry than to silently drop a
        # real chat model whose mode field a vendor PR forgot to set).
        lower = model_id.lower()
        return not any(hint in lower for hint in _NON_CHAT_NAME_HINTS)
    # mode was a non-string or an unrecognised string → drop, with a
    # debug-log so we'd notice if LiteLLM adds new modes.
    logger.debug("LiteLLM entry %r has unrecognised mode=%r — dropping", model_id, mode)
    return False


def _looks_like_model_id(value: str) -> bool:
    """Reject keys that are clearly LiteLLM's own metadata, not models.

    LiteLLM puts a ``sample_spec`` row at the top of the file that
    documents the schema with placeholder values. It also occasionally
    ships internal sentinel keys. A real model id is short, contains
    only safe chars, and isn't the literal string ``sample_spec``.
    """
    if not value or value == "sample_spec":
        return False
    if len(value) > 200:
        return False
    # Allow alnum, dash, underscore, dot, slash, colon. Reject spaces,
    # quotes, control characters — those are never real model ids.
    return bool(re.fullmatch(r"[A-Za-z0-9._/\-:@+]+", value))


def _derive_display_name(model_id: str) -> str:
    """Return a UI-friendly display name for a model id.

    Strategy: keep the bare model id verbatim, just uppercasing a small
    set of well-known acronyms when they appear as a leading segment.
    Any "smart" word-split / title-casing we tried turned ``gpt-4o`` into
    ``Gpt 4o`` and ``glm-4.6`` into ``Glm 4.6`` — worse than the literal
    vendor id. Frontends that want fancier formatting can transform
    further; here we prioritise being faithful to what the vendor calls
    the model.
    """
    bare = model_id.rsplit("/", 1)[-1]
    # Uppercase common acronym prefixes so e.g. ``gpt-4o`` → ``GPT-4o``.
    # Limited list — anything not matched stays verbatim, which is
    # always safe.
    for acronym in ("gpt", "glm", "vl", "tts", "stt"):
        prefix = f"{acronym}-"
        if bare.startswith(prefix):
            return acronym.upper() + bare[len(acronym):]
    return bare


def _validate_and_extract(payload: object) -> dict[str, list[ModelEntry]]:
    """Apply layer-2 protection: validate the parsed JSON.

    Returns a grouped {provider_id: [ModelEntry, ...]} map. Raises
    ``LiteLLMFetchFailed`` if the top-level shape is wrong. Entries
    that fail per-row validation are silently dropped (one row's bad
    metadata shouldn't blow up the whole refresh) but counted in a
    log line so we can spot a degraded LiteLLM JSON release.
    """
    if not isinstance(payload, dict):
        raise LiteLLMFetchFailed(
            f"top-level JSON must be a dict, got {type(payload).__name__}",
        )
    if not payload:
        raise LiteLLMFetchFailed("top-level dict is empty")

    known_providers = set()
    out: dict[str, list[ModelEntry]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    rows_total = 0
    rows_kept = 0
    rows_unknown_provider = 0

    for model_id, entry in payload.items():
        rows_total += 1
        if not isinstance(model_id, str) or not _looks_like_model_id(model_id):
            continue
        if not isinstance(entry, dict):
            continue

        provider_id = entry.get("litellm_provider")
        if not isinstance(provider_id, str) or not provider_id:
            continue

        # Drop providers we don't ship support for. Adding a new vendor
        # is a one-line change in providers.py — no need for the catalog
        # to surface every random Bedrock subprovider LiteLLM tracks.
        provider_defaults = get_provider_defaults(provider_id)
        if provider_defaults is None:
            rows_unknown_provider += 1
            continue

        if not _is_chat_entry(entry, model_id):
            continue

        # Strip any "provider/" prefix from the model id so what we
        # store matches what the vendor /chat/completions endpoint
        # actually expects. (Dedupe MUST use the bare id — LiteLLM
        # occasionally ships the same model both as ``"gpt-4o"`` and
        # ``"openai/gpt-4o"`` and we want to keep just one row.)
        bare_model = model_id.rsplit("/", 1)[-1] if "/" in model_id else model_id

        pair = (provider_id, bare_model)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        # Robust int coercion — LiteLLM occasionally has these as
        # floats (older PRs) or strings (very rare).
        def _as_int(key: str, default: int) -> int:
            v = entry.get(key)
            if isinstance(v, bool):  # bool is subclass of int — exclude
                return default
            if isinstance(v, (int, float)):
                return int(v)
            if isinstance(v, str):
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    return default
            return default

        out.setdefault(provider_id, []).append(
            ModelEntry(
                provider=provider_id,
                model=bare_model,
                display_name=_derive_display_name(bare_model),
                supports_function_calling=bool(
                    entry.get("supports_function_calling", False),
                ),
                context_window=_as_int("max_input_tokens", 0)
                    or _as_int("max_tokens", 128_000),
                max_output_tokens=_as_int("max_output_tokens", 4_096),
                supports_vision=bool(entry.get("supports_vision", False)),
            )
        )
        known_providers.add(provider_id)
        rows_kept += 1

    logger.info(
        "LiteLLM catalog parsed: %d rows total, %d kept across %d providers "
        "(%d rows for unknown providers skipped)",
        rows_total, rows_kept, len(known_providers), rows_unknown_provider,
    )

    if not out:
        # An empty result after parsing a non-empty input means our
        # provider filter was too narrow OR LiteLLM completely changed
        # the schema. Either way, treat as failure so the caller falls
        # back to last-known-good instead of nuking the cache.
        raise LiteLLMFetchFailed(
            f"no entries matched after filtering ({rows_total} input rows)",
        )

    return out


async def fetch_litellm_catalog(
    *,
    url: str | None = None,
    timeout: float = _HTTP_TIMEOUT_S,
    retries: int = _HTTP_RETRIES,
) -> dict[str, list[ModelEntry]]:
    """Fetch + parse + validate the LiteLLM model registry.

    Layer 1 (HTTP retry): up to ``retries + 1`` attempts, exponential
    backoff in between. Network errors / 5xx are retryable; 4xx is
    NOT (a 404 on the URL is a config bug, not a transient blip).

    Layer 2 (schema validate): parse + validate happens BEFORE any
    cache write. Pipeline only persists what this function returns.

    Layer 3 (last-known-good): NOT handled here — this function just
    raises ``LiteLLMFetchFailed`` on terminal failure. The caller
    (``pipeline.refresh_catalog``) catches it and reads the previous
    Redis + DB snapshot.
    """
    target = url or LITELLM_CATALOG_URL
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(target)
                # 4xx is non-retryable (URL / auth misconfiguration);
                # 5xx and network errors fall through to retry.
                if 400 <= resp.status_code < 500:
                    raise LiteLLMFetchFailed(
                        f"non-retryable HTTP {resp.status_code} from {target}",
                    )
                resp.raise_for_status()
                payload = resp.json()
        except LiteLLMFetchFailed:
            # 4xx — give up immediately, don't burn retries.
            raise
        except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < retries:
                # Brief backoff before retry. 0.5s is enough to clear
                # a CDN hiccup without blocking the cron worker long.
                await asyncio.sleep(0.5)
                logger.warning(
                    "LiteLLM fetch attempt %d failed (%s: %s) — retrying",
                    attempt + 1, type(exc).__name__, exc,
                )
                continue
            logger.error(
                "LiteLLM fetch exhausted %d attempts: %s: %s",
                retries + 1, type(exc).__name__, exc,
            )
            raise LiteLLMFetchFailed(
                f"fetch failed after {retries + 1} attempts: {exc}",
            ) from exc
        else:
            # Success path — validate + return.
            return _validate_and_extract(payload)

    # Defensive — the loop always exits via return or raise.
    raise LiteLLMFetchFailed(
        f"unreachable: loop exited without result (last_exc={last_exc})",
    )
