"""Bounded JSON protocol shared by the application, broker and ML interpreter.

No pickle, executable module names, credentials or arbitrary paths on the wire.
The configured broker, not a request, selects the model and interpreter.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import os
import socket
import struct
from typing import BinaryIO

from .errors import ProtocolError

VERSION = 1
MAX_FRAME = 4 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
MAX_ITEMS = 32
ROLES = {"embedding", "reranking", "transcription", "alignment"}
PRIORITIES = {"interactive": 0, "background": 10}
LOCAL_EMBEDDING_CONTRACT = "sentence-transformer-explicit-prompts-v1"


def loads(raw: bytes):
    if len(raw) > MAX_FRAME:
        raise ProtocolError("frame_too_large")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ProtocolError("duplicate_key")
            value[key] = item
        return value

    def invalid(_):
        raise ProtocolError("nonfinite_json")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("invalid_json") from exc


def frame(value) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProtocolError("invalid_json") from exc
    if not 0 < len(raw) <= MAX_FRAME:
        raise ProtocolError("frame_too_large")
    return struct.pack("!I", len(raw)) + raw


def frame_size(header: bytes) -> int:
    if len(header) != 4:
        raise ProtocolError("incomplete_frame")
    size = struct.unpack("!I", header)[0]
    if not 0 < size <= MAX_FRAME:
        raise ProtocolError("frame_too_large")
    return size


async def receive(reader: asyncio.StreamReader):
    size = frame_size(await reader.readexactly(4))
    return loads(await reader.readexactly(size))


async def send(writer: asyncio.StreamWriter, value) -> None:
    writer.write(frame(value))
    await writer.drain()


def read_sync(stream: BinaryIO):
    header = stream.read(4)
    if not header:
        raise EOFError
    size = frame_size(header)
    parts, remaining = [], size
    while remaining:
        part = stream.read(remaining)
        if not part:
            raise ProtocolError("incomplete_frame")
        parts.append(part)
        remaining -= len(part)
    return loads(b"".join(parts))


def request(value: dict) -> dict:
    expected = {
        "version",
        "id",
        "role",
        "binding",
        "operation",
        "texts",
        "query",
        "priority",
        "timeout",
    }
    if isinstance(value, dict) and value.get("role") in ("transcription", "alignment"):
        expected = (expected - {"texts", "query"}) | {"audio", "text", "language"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ProtocolError("invalid_request")
    if type(value["version"]) is not int or value["version"] != VERSION:
        raise ProtocolError("invalid_version")
    if not isinstance(value["id"], str) or not re.fullmatch(
        "[0-9a-f]{32}", value["id"]
    ):
        raise ProtocolError("invalid_id")
    if (
        not isinstance(value["role"], str)
        or not isinstance(value["priority"], str)
        or value["role"] not in ROLES
        or value["priority"] not in PRIORITIES
    ):
        raise ProtocolError("invalid_role_or_priority")
    binding = value["binding"]
    if not isinstance(binding, str) or not re.fullmatch("[0-9a-f]{64}", binding):
        raise ProtocolError("invalid_binding")
    duration = value["timeout"]
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 < duration <= 600
    ):
        raise ProtocolError("invalid_timeout")
    if value["role"] in ("transcription", "alignment"):
        from .audio import validate_audio_request

        return validate_audio_request(value)
    texts, query = value["texts"], value["query"]
    if not isinstance(texts, list) or not 1 <= len(texts) <= MAX_ITEMS:
        raise ProtocolError("invalid_text_count")
    if any(not isinstance(t, str) or not t.strip() for t in texts) or not isinstance(
        query, str
    ):
        raise ProtocolError("invalid_text")
    if sum(len(t.encode()) for t in [*texts, query]) > MAX_TEXT_BYTES:
        raise ProtocolError("input_too_large")
    if value["role"] == "embedding":
        if value["operation"] not in {"query", "passages"} or query:
            raise ProtocolError("invalid_operation")
        if value["operation"] == "query" and len(texts) != 1:
            raise ProtocolError("invalid_query_count")
    elif value["operation"] != "rank" or not query.strip():
        raise ProtocolError("invalid_operation")
    return value


def validate_values(values, *, role: str, count: int, dimension: int) -> list:
    if not isinstance(values, list) or len(values) != count:
        raise ProtocolError("output_count_mismatch")
    rows = values if role == "embedding" else [values]
    for row in rows:
        if not isinstance(row, list) or (role == "embedding" and len(row) != dimension):
            raise ProtocolError("output_dimension_mismatch")
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in row):
            raise ProtocolError("nonfinite_output")
        if role == "embedding" and not any(x != 0 for x in row):
            raise ProtocolError("zero_embedding")
    return values


def same_user(sock) -> bool:
    if not hasattr(socket, "SO_PEERCRED"):
        return False
    _, uid, _ = struct.unpack(
        "3i",
        sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")),
    )
    return uid == os.getuid()


def validate_output(task, values, *, dimension):
    if task["role"] in ("transcription", "alignment"):
        from .audio import validate_audio_result

        return validate_audio_result(task, values)
    return validate_values(
        values, role=task["role"], count=len(task["texts"]), dimension=dimension
    )
