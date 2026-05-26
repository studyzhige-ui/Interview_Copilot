"""Pure-Python magic-byte file validation for uploads.

Why this exists
---------------
Filename extension and Content-Type header are client-controlled. A malicious
client can rename ``evil.exe`` to ``resume.pdf`` and send
``Content-Type: application/pdf``; without inspecting the actual file body,
the upload pipeline writes it to S3 and downstream parsers either crash or,
worse, execute embedded payloads.

This module reads the first ~16 bytes of the upload and compares against a
small dictionary of known file-format signatures ("magic bytes"). It mirrors
the pattern already used in ``app.api.auth._matches_magic`` for avatar
uploads — kept pure-Python on purpose so Windows installs work without the
``libmagic`` system library.

Scope
-----
We only need to validate the **handful** of upload types this app actually
accepts:

  * ``audio``   — mp3, wav, m4a, flac, ogg, mp4 (audio track), webm
  * ``resume``  — pdf, docx, txt, md
  * ``jd``      — same as resume (uploaded job description files)

Plain text (txt/md) has no reliable magic header — we accept any non-binary
body for those, falling back to a heuristic that it contains no NUL bytes
in the first 4 KiB.

Image avatars are validated separately by ``app.api.auth`` because they
have stricter rules (size, dimension-relevant body shape).
"""
from __future__ import annotations

import logging
from tempfile import SpooledTemporaryFile
from typing import Literal

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

# Size at which SpooledTemporaryFile rolls over from RAM to disk.
# Audio uploads (up to 500 MB) MUST not sit in RAM — that's the whole
# point of P6-E. Resume/JD (up to 10 MB) can fit comfortably, but
# uniform threshold keeps the upload code branch-free.
_SPOOL_ROLLOVER_BYTES = 1024 * 1024  # 1 MiB
_DEFAULT_CHUNK_BYTES = 64 * 1024     # 64 KiB


# ── Magic-byte signatures ───────────────────────────────────────────────
# Each entry maps a friendly format label to the list of byte prefixes
# that identify it. Containers (mp4, m4a, webm) need a small offset check;
# we model those separately in ``_matches_container``.

_AUDIO_MAGIC: dict[str, tuple[bytes, ...]] = {
    # mp3: either an ID3v2 tag header or a raw MPEG frame sync.
    "mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    # WAV is RIFF<size:4>WAVE — handled specially below (4-byte gap).
    "wav": (b"RIFF",),
    # FLAC magic.
    "flac": (b"fLaC",),
    # Ogg (Vorbis/Opus).
    "ogg": (b"OggS",),
    # AAC ADTS frame syncs (with/without CRC).
    "aac": (b"\xff\xf1", b"\xff\xf9"),
}

_RESUME_MAGIC: dict[str, tuple[bytes, ...]] = {
    # PDF documents start with "%PDF-".
    "pdf": (b"%PDF-",),
    # DOCX and other Office Open XML formats are ZIP archives; we accept any
    # PK\x03\x04 here and rely on the extraction step to reject malformed ZIPs.
    "docx": (b"PK\x03\x04",),
}


def _matches_riff_with_subtype(body: bytes, subtype: bytes) -> bool:
    """RIFF<size:4><subtype> — used for WAV (``WAVE``) and WebP."""
    return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == subtype


def _matches_iso_bmff(body: bytes, brands: tuple[bytes, ...]) -> bool:
    """ISO Base Media File Format (mp4/m4a/mov/3gp) — ``....ftypBRAND``.

    Box layout: bytes 0..4 = size, 4..8 = "ftyp", 8..12 = major brand.
    We don't validate the size field; just check ftyp and major brand.
    """
    if len(body) < 12 or body[4:8] != b"ftyp":
        return False
    return body[8:12] in brands


# Major brands that count as "audio/video media we'd send to WhisperX".
_MP4_BRANDS: tuple[bytes, ...] = (
    b"isom", b"iso2", b"mp41", b"mp42",   # generic MP4
    b"M4A ", b"M4B ", b"mp4a",            # audio-only
    b"qt  ",                              # QuickTime mov
    b"3gp4", b"3gp5",                     # 3GP
)


def _looks_like_text(body: bytes, max_check: int = 4096) -> bool:
    """Cheap heuristic: a file is "text" if the first few KiB contain no
    NUL bytes and decode as UTF-8 (or are empty).

    Misses some pathological inputs (UTF-16 with BOM, exotic encodings),
    but for resumes-as-txt/md that's good enough. We're guarding against
    obvious binary files masquerading as ``.txt``.
    """
    sample = body[:max_check]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# ── Per-purpose dispatcher ──────────────────────────────────────────────


def _detect_audio_format(body: bytes) -> str | None:
    """Return the detected audio format name, or None if no magic matches."""
    for fmt, prefixes in _AUDIO_MAGIC.items():
        if fmt == "wav":
            if _matches_riff_with_subtype(body, b"WAVE"):
                return "wav"
            continue
        if any(body.startswith(p) for p in prefixes):
            return fmt
    if _matches_iso_bmff(body, _MP4_BRANDS):
        return "mp4"
    # WebM: EBML header 0x1A 0x45 0xDF 0xA3
    if body.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    # Matroska / MKV uses the same EBML header.
    return None


def _detect_resume_format(body: bytes, declared_ext: str) -> str | None:
    """Return the resume format, falling back to text heuristic for txt/md."""
    for fmt, prefixes in _RESUME_MAGIC.items():
        if any(body.startswith(p) for p in prefixes):
            return fmt
    if declared_ext in {".txt", ".md"} and _looks_like_text(body):
        return "text"
    return None


# ── Per-purpose size ceilings (bytes) ───────────────────────────────────
# Enforced in addition to nginx's global ``client_max_body_size``. These
# are the "business-correct" limits — nginx is a coarser network-layer
# safety net. Bump these only after considering downstream impact (storage
# cost, LLM context budget, transcription latency).

_SIZE_LIMITS_BYTES: dict[str, int] = {
    "audio_clip": 25 * 1024 * 1024,        # 25 MB — short mock-interview clips
    "audio_upload": 500 * 1024 * 1024,     # 500 MB — full interview recordings
    "resume": 10 * 1024 * 1024,            # 10 MB
    "jd": 10 * 1024 * 1024,                # 10 MB
}


Purpose = Literal["audio_clip", "audio_upload", "resume", "jd"]


def _detect(body: bytes, purpose: Purpose, declared_ext: str) -> str | None:
    """Dispatch to the right detector based on purpose. Pure helper —
    works on bytes and never raises."""
    if purpose in {"audio_clip", "audio_upload"}:
        return _detect_audio_format(body)
    if purpose in {"resume", "jd"}:
        return _detect_resume_format(body, declared_ext.lower())
    return None


async def validate_upload_stream(
    file: UploadFile,
    purpose: Purpose,
    declared_ext: str = "",
    *,
    chunk_size: int = _DEFAULT_CHUNK_BYTES,
) -> tuple[str, int, SpooledTemporaryFile]:
    """Stream-validate a FastAPI ``UploadFile`` without ever loading
    the whole body into RAM.

    Returns ``(detected_format, total_size_bytes, body_stream)``. The
    body_stream is a ``SpooledTemporaryFile`` already seeked to 0;
    the caller is responsible for closing it (which deletes the
    on-disk spill if one was created). Hand it to
    ``boto3.upload_fileobj`` directly — both interfaces speak the
    same file-like protocol.

    Pre-P6-E ``validate_upload`` did ``body = await file.read()`` —
    a single 500 MB audio upload pinned half a gigabyte of RAM per
    request. 10 concurrent uploads → 5 GB RAM → OOM. Streaming
    caps per-request RAM at ``_SPOOL_ROLLOVER_BYTES`` (1 MiB);
    everything beyond rolls over to a temp file on disk.

    Raises ``HTTPException(400)`` on:
      * empty body
      * unrecognised magic header
      * size > _SIZE_LIMITS_BYTES[purpose] (checked progressively —
        the request is aborted as soon as we exceed the cap, so
        a malicious 50 GB POST never gets fully buffered)

    Magic detection happens on the FIRST 32 bytes only. The full
    body still gets streamed (for size + spool), but format
    rejection short-circuits before we waste IO on the rest.
    """
    limit = _SIZE_LIMITS_BYTES.get(purpose)
    if limit is None:
        raise HTTPException(500, f"Unknown upload purpose: {purpose}")

    # Phase 1 — read just enough to magic-byte detect. 32 bytes covers
    # every signature we recognise (PDF needs 5, ISO BMFF needs 12,
    # ID3 needs 3, etc).
    head = await file.read(32)
    if not head:
        raise HTTPException(400, "文件内容为空")

    detected = _detect(head, purpose, declared_ext.lower())
    if detected is None:
        logger.warning(
            "Rejected upload: purpose=%s filename=%r declared=%r "
            "(magic header didn't match the purpose whitelist)",
            purpose, file.filename, file.content_type,
        )
        # User-facing error messages — match the legacy text so any
        # FE error-handling regex still works.
        if purpose in {"audio_clip", "audio_upload"}:
            raise HTTPException(
                400,
                "不支持的音频/视频格式（无法识别文件头）。"
                "支持：mp3, wav, m4a, flac, ogg, aac, mp4, webm",
            )
        raise HTTPException(
            400,
            "不支持的文件格式（仅接受 pdf, docx, txt, md，"
            "且文件内容必须与扩展名一致）。",
        )

    # Phase 2 — stream the rest into a spooled temp file, counting
    # size as we go. We've already validated the head; the rest is
    # just transport.
    spool = SpooledTemporaryFile(max_size=_SPOOL_ROLLOVER_BYTES, mode="w+b")
    try:
        spool.write(head)
        total = len(head)
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                mb = limit // (1024 * 1024)
                raise HTTPException(400, f"文件超过 {mb}MB 上限")
            spool.write(chunk)
    except BaseException:
        # Any error path — including the size-exceeded HTTPException —
        # must drop the spool so we don't leak a temp file (or pinned
        # RAM, if it never rolled over to disk).
        spool.close()
        raise

    spool.seek(0)
    return detected, total, spool


async def validate_upload(
    file: UploadFile,
    purpose: Purpose,
    declared_ext: str = "",
) -> bytes:
    """Backward-compat wrapper — small uploads only.

    Returns the full body as bytes. Internally just reads the
    streaming spool back into memory, so this is suitable ONLY
    for uploads whose size cap fits comfortably in RAM (resume
    + JD at 10 MB each). For 500 MB audio uploads, callers MUST
    use :func:`validate_upload_stream` directly.
    """
    detected, _size, spool = await validate_upload_stream(
        file, purpose, declared_ext,
    )
    try:
        return spool.read()
    finally:
        spool.close()
    # detected isn't returned by the legacy contract; callers that
    # need it should migrate to validate_upload_stream.
    _ = detected


__all__ = ["validate_upload", "validate_upload_stream", "Purpose"]
