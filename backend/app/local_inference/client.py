"""Lightweight application client; no downloads, model imports or daemon spawn."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import stat
import time
import uuid

from app.core.execution_errors import ModelOutcomeUnknownError
from .protocol import (
    VERSION,
    frame,
    frame_size,
    loads,
    receive,
    request,
    same_user,
    send,
    validate_output,
)


class LocalInferenceNotStarted(RuntimeError):
    """A definite admission rejection; existing accounting may release allowance."""

    status_code = 429


class LocalInferenceUnknown(ModelOutcomeUnknownError):
    """Never replace an uncertain dispatch with an in-process or online retry."""


def configured_socket_path():
    from app.core.config import settings

    return settings.LOCAL_INFERENCE_SOCKET or str(
        Path(settings.APP_DATA_DIR) / "inference/run/worker.sock"
    )


def check_socket(path: str):
    if not hasattr(socket, "SO_PEERCRED"):
        raise LocalInferenceNotStarted("local_inference_requires_linux_or_wsl2")
    try:
        target = Path(path)
        parent, info = target.parent.lstat(), target.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid()
            or parent.st_mode & 0o077
        ):
            raise ValueError
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise ValueError
    except (OSError, ValueError):
        raise LocalInferenceNotStarted(
            "local_inference_socket_not_ready_or_not_private"
        ) from None


def make_request(
    role, binding, operation, texts, *, query="", priority="interactive", timeout=120
):
    return request(
        dict(
            version=VERSION,
            id=uuid.uuid4().hex,
            role=role,
            binding=binding,
            operation=operation,
            texts=texts,
            query=query,
            priority=priority,
            timeout=timeout,
        )
    )


def checked_response(task, response, dimension):
    if (
        not isinstance(response, dict)
        or response.get("id") != task["id"]
        or response.get("binding") != task["binding"]
    ):
        raise LocalInferenceUnknown("local_inference_response_mismatch")
    rejections = {
        "not_started": {
            "broker_stopping",
            "model_binding_mismatch",
            "duplicate_request",
            "queue_full",
            "queue_deadline",
            "model_not_available",
            "cancelled_before_start",
        },
        "rejected": {"input_exceeds_model_tokens"},
    }
    if (
        response.get("status") in rejections
        and response.get("code") in rejections[response["status"]]
    ):
        # Do not trust arbitrary child-provided text as a user-facing exception.
        raise LocalInferenceNotStarted("local_inference_request_rejected")
    if response.get("status") != "completed":
        raise LocalInferenceUnknown("local_inference_outcome_unknown")
    return validate_output(task, response.get("values"), dimension=dimension)


def make_audio_request(
    role, binding, pcm, *, text="", language=None, priority="background", timeout=120
):
    from .audio import pcm_payload

    return request(
        dict(
            version=VERSION,
            id=uuid.uuid4().hex,
            role=role,
            binding=binding,
            operation="transcribe" if role == "transcription" else "align",
            audio=pcm_payload(pcm),
            text=text,
            language=language,
            priority=priority,
            timeout=timeout,
        )
    )


class Client:
    def __init__(self, socket_path: str, *, timeout=120):
        if type(timeout) not in (int, float) or not 0 < timeout <= 600:
            raise ValueError("invalid_client_timeout")
        self.socket_path, self.timeout = socket_path, timeout

    def call(self, task, *, dimension):
        request(task)
        packet = frame(task)
        check_socket(self.socket_path)
        deadline = time.monotonic() + self.timeout
        dispatched = False
        try:
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(min(self.timeout, 5))
                conn.connect(self.socket_path)
                if not same_user(conn):
                    raise LocalInferenceNotStarted("local_inference_peer_mismatch")
                conn.settimeout(max(0.001, deadline - time.monotonic()))
                dispatched = True
                conn.sendall(packet)

                def read(n):
                    parts = []
                    while n:
                        left = deadline - time.monotonic()
                        if left <= 0:
                            raise TimeoutError
                        conn.settimeout(left)
                        part = conn.recv(n)
                        if not part:
                            raise EOFError
                        parts.append(part)
                        n -= len(part)
                    return b"".join(parts)

                response = loads(read(frame_size(read(4))))
                return checked_response(task, response, dimension)
        except LocalInferenceNotStarted:
            raise
        except Exception:
            if not dispatched:
                raise LocalInferenceNotStarted(
                    "local_inference_connection_failed"
                ) from None
            raise LocalInferenceUnknown(
                "local_inference_response_unconfirmed"
            ) from None

    async def acall(self, task, *, dimension):
        request(task)
        packet = frame(task)  # Validate size before connecting or marking sent.
        check_socket(self.socket_path)
        writer = None
        dispatched = False
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(self.socket_path, limit=65536),
                    min(5, self.timeout),
                )
                if not same_user(writer.get_extra_info("socket")):
                    raise LocalInferenceNotStarted("local_inference_peer_mismatch")
                dispatched = True
                writer.write(packet)
                await writer.drain()
                return checked_response(task, await receive(reader), dimension)
        except LocalInferenceNotStarted:
            raise
        except Exception:
            if not dispatched:
                raise LocalInferenceNotStarted(
                    "local_inference_connection_failed"
                ) from None
            raise LocalInferenceUnknown(
                "local_inference_response_unconfirmed"
            ) from None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 1)
                except (OSError, TimeoutError):
                    pass

    async def status(self):
        check_socket(self.socket_path)
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(self.socket_path), 5
        )
        try:
            if not same_user(writer.get_extra_info("socket")):
                raise LocalInferenceNotStarted("local_inference_peer_mismatch")
            async with asyncio.timeout(5):
                await send(writer, {"version": 1, "operation": "status"})
                return await receive(reader)
        finally:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), 1)
