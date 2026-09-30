"""Bounded, checksum-verified source clips. No model calls or public media URLs."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import io
from pathlib import Path
from tempfile import TemporaryDirectory
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
    from app.core.config import settings
    from app.core.storage import is_local_uri, parse_local_uri, parse_s3_uri

    if is_local_uri(storage_uri):
        yield str(parse_local_uri(storage_uri))
        return
    if not storage_uri.startswith("s3://"):
        raise CommandError("conflict", "原录音存储类型不支持安全回放")
    bucket, key = parse_s3_uri(storage_uri)
    if bucket != settings.S3_BUCKET_NAME:
        raise CommandError("conflict", "原录音不在受控存储范围内")

    import boto3
    from botocore.config import Config

    # A stalled object store cannot occupy the bounded playback pool forever.
    with boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
        endpoint_url=settings.AWS_ENDPOINT_URL,
        config=Config(
            connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}
        ),
    ) as client:
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        try:
            size = response.get("ContentLength")
            if type(size) is not int or not 0 < size <= max_bytes:
                raise ValueError("audio_input_size_invalid")
            with TemporaryDirectory(prefix="interview-playback-object-") as root:
                path = Path(root) / "source.audio"
                total = 0
                with path.open("xb") as output:
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("playback_deadline")
                        block = body.read(64 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > max_bytes or total > size:
                            raise ValueError("audio_input_size_invalid")
                        output.write(block)
                if total != size:
                    raise ValueError("audio_source_changed")
                yield str(path)
        finally:
            body.close()


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
