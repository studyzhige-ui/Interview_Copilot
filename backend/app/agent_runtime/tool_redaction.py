"""Server-side redaction for Tool audit and presentation projections.

Tool handlers still receive their original typed inputs.  This module creates
redacted copies for durable audit, SSE, replay, and recovery surfaces so a
credential returned by an untrusted Tool cannot be copied into user-visible or
long-lived state.
"""

from __future__ import annotations

import json
import re
from typing import Any

REDACTED_TOOL_VALUE = "[REDACTED]"
_MAX_REDACTION_DEPTH = 32

_SENSITIVE_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "auth",
        "authorization",
        "authtoken",
        "awssecretaccesskey",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "csrftoken",
        "idtoken",
        "password",
        "passwd",
        "passphrase",
        "privatekey",
        "proxyauthorization",
        "refreshtoken",
        "secret",
        "secretkey",
        "sessioncookie",
        "sessionid",
        "sessiontoken",
        "setcookie",
        "signingkey",
        "token",
        "xapikey",
        "xcsrftoken",
        "xsrftoken",
    }
)
_SENSITIVE_KEY_SUFFIXES = (
    "accesstoken",
    "apikey",
    "authtoken",
    "clientsecret",
    "credential",
    "password",
    "passwd",
    "passphrase",
    "privatekey",
    "refreshtoken",
    "secret",
    "sessiontoken",
    "signingkey",
    "token",
)

_SENSITIVE_LABEL = (
    r"authorization|proxy[-_ ]?authorization|api[-_ ]?key|x[-_ ]?api[-_ ]?key|"
    r"client[-_ ]?secret|access[-_ ]?token|refresh[-_ ]?token|id[-_ ]?token|"
    r"auth[-_ ]?token|csrf[-_ ]?token|xsrf[-_ ]?token|session[-_ ]?(?:id|token)|"
    r"password|passwd|passphrase|private[-_ ]?key|signing[-_ ]?key|"
    r"credentials?|secret(?:[-_ ]?key)?|cookie|set[-_ ]?cookie|token"
)
_CREDENTIAL_HEADER_RE = re.compile(
    r"(?i)(\b(?:authorization|proxy[-_ ]?authorization|cookie|set[-_ ]?cookie)"
    r"\s*:\s*)[^\r\n]+"
)
_QUOTED_LABELED_VALUE_RE = re.compile(
    rf"(?i)(?P<prefix>\b(?:{_SENSITIVE_LABEL})\b\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
)
_UNQUOTED_LABELED_VALUE_RE = re.compile(
    rf"(?i)(?P<prefix>\b(?:{_SENSITIVE_LABEL})\b\s*[:=]\s*)"
    r"(?P<value>[^\s,;&]+)"
)
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(?P<scheme>bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_URL_USERINFO_RE = re.compile(
    r"(?i)(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_OBVIOUS_CREDENTIAL_RES = (
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
    re.compile(r"\btvly-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:sk|rk)[-_](?:live[-_]|test[-_]|proj[-_])?[A-Za-z0-9_-]{12,}\b"),
)


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def redact_tool_text(value: str) -> str:
    """Redact credentials from a Tool-derived string.

    Complete JSON objects and arrays are parsed first so sensitive field names
    receive the same recursive treatment as typed payloads.  Pattern matching
    then covers exception text, headers, URLs, and obvious credential formats.
    """

    stripped = value.strip()
    if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            pass
        else:
            if isinstance(parsed, (dict, list)):
                redacted = redact_tool_value(parsed)
                encoded = json.dumps(redacted, ensure_ascii=False)
                leading_chars = len(value) - len(value.lstrip())
                trailing_chars = len(value) - len(value.rstrip())
                leading = value[:leading_chars]
                trailing = (
                    value[len(value) - trailing_chars :] if trailing_chars else ""
                )
                return f"{leading}{encoded}{trailing}"

    redacted_text = _PRIVATE_KEY_RE.sub(REDACTED_TOOL_VALUE, value)
    redacted_text = _URL_USERINFO_RE.sub(
        lambda match: f"{match.group('scheme')}{REDACTED_TOOL_VALUE}@",
        redacted_text,
    )
    redacted_text = _CREDENTIAL_HEADER_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED_TOOL_VALUE}",
        redacted_text,
    )
    redacted_text = _QUOTED_LABELED_VALUE_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('value')[0]}"
            f"{REDACTED_TOOL_VALUE}{match.group('value')[-1]}"
        ),
        redacted_text,
    )
    redacted_text = _UNQUOTED_LABELED_VALUE_RE.sub(
        lambda match: f"{match.group('prefix')}{REDACTED_TOOL_VALUE}",
        redacted_text,
    )
    redacted_text = _AUTH_SCHEME_RE.sub(
        lambda match: f"{match.group('scheme')} {REDACTED_TOOL_VALUE}",
        redacted_text,
    )
    for credential_re in _OBVIOUS_CREDENTIAL_RES:
        redacted_text = credential_re.sub(REDACTED_TOOL_VALUE, redacted_text)
    return redacted_text


def redact_tool_value(value: Any, *, _depth: int = 0) -> Any:
    """Return a recursively redacted copy of a JSON-like Tool value."""

    if _depth >= _MAX_REDACTION_DEPTH:
        return REDACTED_TOOL_VALUE
    if isinstance(value, dict):
        return {
            key: (
                REDACTED_TOOL_VALUE
                if _is_sensitive_key(key)
                else redact_tool_value(item, _depth=_depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_tool_value(item, _depth=_depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_tool_value(item, _depth=_depth + 1) for item in value)
    if isinstance(value, str):
        return redact_tool_text(value)
    return value
