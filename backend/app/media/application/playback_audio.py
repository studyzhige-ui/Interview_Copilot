"""Bounded, checksum-verified source clips. No model calls or public media URLs."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import io
import time
import wave

from app.core.command_errors import CommandError
from app.local_inference.audio import SAMPLE_RATE
from app.media.application.evidence_source import capture_evidence_source
from app.media.application.pcm_stream import PCMStream

MAX_CLIP_SECONDS = 30
PLAYBACK_DEADLINE_SECONDS = 120


@contextmanager
def _local_source(storage_uri: str, *, max_bytes: int, deadline: float):
    from app.core.storage import materialize_object

    if time.monotonic() >= deadline:
        raise TimeoutError("playback_deadline")
    with materialize_object(
        storage_uri, max_bytes=max_bytes, deadline=deadline
    ) as path:
        if time.monotonic() >= deadline:
            raise TimeoutError("playback_deadline")
        yield path


async def _decode(path, *, first, last, max_bytes, max_ms, timeout):
    pcm = bytearray()
    cursor = 0
    async with asyncio.timeout(timeout):
        async with PCMStream(path, max_bytes=max_bytes, max_ms=max_ms) as source:
            async for block in source:
                end = cursor + len(block) // 2
                lower, upper = max(first, cursor), min(last, end)
                if lower < upper:
                    pcm.extend(block[(lower - cursor) * 2 : (upper - cursor) * 2])
                cursor = end
                if cursor >= last:
                    break
    if len(pcm) != (last - first) * 2:
        raise ValueError("audio_decode_incomplete")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)
    return buffer.getvalue()


def render_clip(selection, *, max_bytes: int, max_ms: int) -> bytes:
    """The synchronous worker owns snapshots and FFmpeg even after HTTP loss.

    Decode from the pinned source timeline and slice by sample indices. This is
    bounded-memory offline review playback, not a real-time media transport.
    """
    if (
        type(selection.first_sample) is not int
        or type(selection.last_sample) is not int
        or not 0 <= selection.first_sample < selection.last_sample
        or selection.last_sample - selection.first_sample
        > MAX_CLIP_SECONDS * SAMPLE_RATE
    ):
        raise CommandError("invalid", "请选择不超过 30 秒的有效原录音片段")
    deadline = time.monotonic() + PLAYBACK_DEADLINE_SECONDS
    try:
        with _local_source(
            selection.storage_uri, max_bytes=max_bytes, deadline=deadline
        ) as path:
            with capture_evidence_source(
                path,
                file_asset_id=selection.file_asset_id,
                # The evidence hash is mandatory, even for old asset-only tokens.
                file_asset_version=f"sha256:{selection.sha256}",
                max_bytes=max_bytes,
            ) as source:
                if (
                    selection.size_bytes is not None
                    and source.size_bytes != selection.size_bytes
                ):
                    raise ValueError("audio_source_changed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("playback_deadline")
                result = asyncio.run(
                    _decode(
                        source.path,
                        first=selection.first_sample,
                        last=selection.last_sample,
                        max_bytes=max_bytes,
                        max_ms=max_ms,
                        timeout=remaining,
                    )
                )
        return result
    except CommandError:
        raise
    except ValueError as exc:
        raise CommandError(
            "conflict", "原录音与转写证据不一致或无法完整解码，未提供替代音频"
        ) from exc
    except Exception as exc:
        raise CommandError("unavailable", "原录音暂时无法回放，请稍后重试") from exc
