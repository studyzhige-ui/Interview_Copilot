"""Bounded local audio measurement before a priced ASR request.

Container headers may omit duration (notably browser WebM). Decode to mono PCM
in that case, count without buffering the clip, and kill on size/time limits.
Unknown duration never becomes zero billable audio. Commands are argv arrays,
use a local absolute file, and disallow network protocols.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import selectors
import subprocess
import time
from pathlib import Path
from app.core.config import settings
from app.usage.pricing import quantities


def audio_units(file_path: str) -> dict[str, int]:
    path = Path(file_path).resolve(strict=True)
    size = path.stat().st_size
    if not path.is_file() or size <= 0 or size > settings.USAGE_AUDIO_MAX_BYTES:
        raise ValueError("audio_input_size_invalid")
    try:
        output = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
        if len(output.stdout) > 8192:
            raise ValueError("audio_probe_output_excessive")
        seconds = float(
            json.loads(output.stdout).get("format", {}).get("duration", "nan")
        )
    except (ValueError, subprocess.SubprocessError, OSError):
        seconds = float("nan")
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = _decoded_seconds(path)
    milliseconds = math.ceil(seconds * 1000)
    if not 0 < milliseconds <= settings.USAGE_AUDIO_MAX_MS:
        raise ValueError("audio_duration_exceeds_limit")
    return quantities({"requests": 1, "audio_ms": milliseconds, "bytes": size})


def _decoded_seconds(path: Path) -> float:
    # PCM16, mono, 8 kHz -> 16,000 bytes/second. stdout is drained in fixed
    # chunks; stderr cannot fill a pipe. Temporary child is always reaped.
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ar",
        "8000",
        "-ac",
        "1",
        "-f",
        "s16le",
        "pipe:1",
    ]
    count = 0
    deadline = time.monotonic() + settings.USAGE_AUDIO_PROBE_SECONDS
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as process:
        try:
            assert process.stdout is not None
            # selectors work with POSIX pipes (deployed API/worker are Linux).
            # Windows installs must use FFprobe-duration or an explicit supported
            # audio conversion, not silently hang on an unsupported selector.
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("audio_measurement_deadline")
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > settings.USAGE_AUDIO_MAX_MS * 16:
                        raise ValueError("audio_duration_exceeds_limit")
            if (
                process.wait(timeout=max(0.1, deadline - time.monotonic())) != 0
                or count == 0
            ):
                raise ValueError("audio_duration_unavailable")
            return count / 16000
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def descriptor(cfg, file_path: str, language: str | None, units: dict):
    # Do not persist filenames or content. HMAC of local identity is only used
    # to bind the physical dispatch. Callers supply an owned, immutable upload.
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return dict(
        meter="transcription",
        provider=cfg.provider_id,
        model=cfg.model,
        content={
            "content_sha256": digest.hexdigest(),
            "language": language,
            "size": units["bytes"],
            "duration": units["audio_ms"],
            "destination": cfg.provider.api_base,
        },
        units=units,
    )
