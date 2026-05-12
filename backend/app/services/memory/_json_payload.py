"""Internal JSON helpers shared by the memory subpackage."""

import json
import re
from typing import Any


def _extract_json_payload(raw_text: str) -> Any:
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        raise json.JSONDecodeError("empty", raw_text, 0)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", raw_text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(1))


def _normalize_key(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return normalized[:100] or "memory"


__all__ = ["_extract_json_payload", "_normalize_key"]
