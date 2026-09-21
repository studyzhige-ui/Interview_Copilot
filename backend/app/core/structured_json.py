"""Bounded, duplicate-free JSON at untrusted structured-output boundaries."""

import json


def strict_json(text: str, *, max_bytes: int = 1_000_000):
    """No duplicate keys, NaN, coercion, or unbounded model response parsing."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise ValueError("JSON input exceeds capacity")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("nonfinite JSON number")

    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    except RecursionError:
        raise ValueError("JSON input nesting exceeds parser capacity") from None
