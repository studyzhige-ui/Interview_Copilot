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
from typing import Literal

from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)


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


async def validate_upload(
    file: UploadFile,
    purpose: Purpose,
    declared_ext: str = "",
) -> bytes:
    """Validate a FastAPI ``UploadFile`` against ``purpose``'s rules.

    Returns the file body as bytes (already read into memory). The caller
    should write these bytes to storage rather than calling
    ``file.read()`` again — UploadFile's underlying stream is single-pass.

    Raises ``HTTPException(400)`` on size or magic-byte failure. The error
    message is user-facing Chinese.

    Parameters
    ----------
    file
        Incoming upload.
    purpose
        Which whitelist + size ceiling to apply.
    declared_ext
        File extension (with leading dot, lower-case). Used only as a
        tie-breaker for plain-text resumes — extension alone is never
        the security boundary.
    """
    limit = _SIZE_LIMITS_BYTES.get(purpose)
    if limit is None:
        # Programming error, not a user error.
        raise HTTPException(500, f"Unknown upload purpose: {purpose}")

    body = await file.read()
    size = len(body)

    if size == 0:
        raise HTTPException(400, "文件内容为空")
    if size > limit:
        mb = limit // (1024 * 1024)
        raise HTTPException(400, f"文件超过 {mb}MB 上限")

    if purpose in {"audio_clip", "audio_upload"}:
        detected = _detect_audio_format(body)
        if detected is None:
            logger.warning(
                "Rejected upload: purpose=%s filename=%r declared=%r "
                "(no recognised audio magic header in first 16 bytes)",
                purpose, file.filename, file.content_type,
            )
            raise HTTPException(
                400,
                "不支持的音频/视频格式（无法识别文件头）。"
                "支持：mp3, wav, m4a, flac, ogg, aac, mp4, webm",
            )
        return body

    if purpose in {"resume", "jd"}:
        detected = _detect_resume_format(body, declared_ext.lower())
        if detected is None:
            logger.warning(
                "Rejected upload: purpose=%s filename=%r declared=%r "
                "(magic header doesn't match pdf/docx and body isn't text)",
                purpose, file.filename, file.content_type,
            )
            raise HTTPException(
                400,
                "不支持的文件格式（仅接受 pdf, docx, txt, md，"
                "且文件内容必须与扩展名一致）。",
            )
        return body

    # Unreachable: Purpose is a Literal[…] guarded above.
    raise HTTPException(500, f"Unknown upload purpose: {purpose}")


__all__ = ["validate_upload", "Purpose"]
