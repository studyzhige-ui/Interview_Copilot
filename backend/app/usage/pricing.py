"""Exact, frozen rate cards. No guessed vendor prices, floats or currency mixing.

Rates are decimal currency-per-unit strings. An omitted rate is NOT zero.
An administrator may explicitly price a resource at zero. Provider invoice
reconciliation remains distinct from this application's rated usage estimates.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_CEILING, localcontext
from functools import lru_cache

UNITS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "audio_ms",
        "characters",
        "documents",
        "pages",
        "bytes",
        "requests",
        "external_requests",
        "tool_invocations",
    }
)
MAX_COUNTER = 2**63 - 1
MAX_COST = 10**15


def quantities(value: dict | None) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("usage_units_must_be_object")
    if set(value) - UNITS:
        raise ValueError("unknown_usage_unit")
    if any(type(v) is not int or not 0 <= v <= MAX_COUNTER for v in value.values()):
        raise ValueError("invalid_usage_quantity")
    if any(v > 2**31 - 1 for k, v in value.items() if k.endswith("tokens")):
        raise ValueError("invalid_usage_token_quantity")
    return dict(value)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_rate_card_key")
        result[key] = value
    return result


@lru_cache(maxsize=8)
def rate_catalog(raw: str) -> dict:
    data = json.loads(raw, object_pairs_hook=_unique_pairs)
    if not isinstance(data, dict) or len(data) > 1000:
        raise ValueError("invalid_rate_card")
    for key, rates in data.items():
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 460
            or not isinstance(rates, dict)
            or not rates
        ):
            raise ValueError("invalid_rate_card")
        if set(rates) - UNITS:
            raise ValueError("unknown_rate_unit")
        for price in rates.values():
            if not isinstance(price, str) or len(price) > 40:
                raise ValueError("rate_requires_decimal_string")
            number = Decimal(price)
            if (
                not number.is_finite()
                or not Decimal(0) <= number <= Decimal(1000000)
                or number.as_tuple().exponent < -18
            ):
                raise ValueError("invalid_unit_rate")
    return data


def freeze(
    *, raw: str, currency: str, meter: str, provider: str, model: str
) -> dict | None:
    # Exact identities only: no model-name substring, vendor fallback, exchange
    # rate lookup or user-supplied ToolResult can change a registered price.
    catalog = rate_catalog(raw)
    key = f"{meter}:{provider}:{model}"
    if key not in catalog:
        return None
    canonical = json.dumps(
        {"currency": currency, "key": key, "rates": catalog[key]}, sort_keys=True
    )
    return {
        **json.loads(canonical),
        "version": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def cost_micros(snapshot: dict | None, units: dict[str, int]) -> int | None:
    if snapshot is None:
        return None
    quantities(units)
    # A card describes its billable units. Non-billable observed metrics need
    # not be priced, but every configured billable unit must have an allowance.
    if set(snapshot["rates"]) - set(units):
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        value = sum(
            (Decimal(v) * units[k] for k, v in snapshot["rates"].items()), Decimal(0)
        )
        result = int((value * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    if result < 0 or result > MAX_COST:
        raise ValueError("usage_cost_out_of_range")
    return result


def model_units(usage, *, anthropic: bool = False) -> dict[str, int] | None:
    """Normalize disjoint token buckets; no double-count of cache tokens."""

    def field(obj, name, default=None):
        return (
            obj.get(name, default)
            if isinstance(obj, dict)
            else getattr(obj, name, default)
        )

    if usage is None:
        return None
    input_count = field(usage, "input_tokens" if anthropic else "prompt_tokens")
    output_count = field(usage, "output_tokens" if anthropic else "completion_tokens")
    if input_count is None or output_count is None:
        return None
    read = (
        field(usage, "cache_read_input_tokens", 0)
        if anthropic
        else field(field(usage, "prompt_tokens_details", {}), "cached_tokens", 0)
    )
    write = field(usage, "cache_creation_input_tokens", 0) if anthropic else 0
    values = quantities(
        {
            "input_tokens": input_count,
            "output_tokens": output_count,
            "cache_read_tokens": read,
            "cache_write_tokens": write,
            "requests": 1,
        }
    )
    if not anthropic:
        if read > input_count:
            raise ValueError("cache_usage_exceeds_input")
        values["input_tokens"] -= read
    return values
