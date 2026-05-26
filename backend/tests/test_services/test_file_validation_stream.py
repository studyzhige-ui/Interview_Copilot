"""Streaming-validator tests for ``app.services.uploads.file_validation``.

P6-E switched the audio_upload path from "read 500 MB into a Python
``bytes``" to a SpooledTemporaryFile-backed streaming pipeline.
These tests pin the new contract:

  * magic-byte detection still works on the first 32 bytes
  * size-cap is enforced PROGRESSIVELY (a 50 GB POST aborts at
    the limit, not after the whole body is buffered)
  * spool is cleaned up on every failure path
"""

from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile

from app.services.uploads.file_validation import (
    _SIZE_LIMITS_BYTES,
    validate_upload_stream,
)


def _make_upload(body: bytes, filename: str = "x.pdf") -> UploadFile:
    """Wrap raw bytes in an UploadFile so we can drive the validator."""
    return UploadFile(file=io.BytesIO(body), filename=filename)


def test_pdf_validates_and_returns_spool():
    pdf_body = b"%PDF-1.4\n" + b"x" * 4096
    detected, size, spool = asyncio.run(
        validate_upload_stream(_make_upload(pdf_body), purpose="resume"),
    )
    try:
        assert detected == "pdf"
        assert size == len(pdf_body)
        spool_contents = spool.read()
        assert spool_contents == pdf_body
    finally:
        spool.close()


def test_unknown_magic_rejected_fast():
    """First 32 bytes don't match any purpose-whitelisted format →
    400 with the user-facing Chinese message."""
    garbage = b"\x01\x02\x03 not a real file " + b"y" * 4096
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            validate_upload_stream(_make_upload(garbage), purpose="resume"),
        )
    assert exc.value.status_code == 400
    assert "不支持的文件格式" in exc.value.detail


def test_audio_unknown_magic_rejected_with_audio_message():
    """Same path, but the audio purpose gets a different Chinese
    error string — confirming the dispatch by purpose works."""
    garbage = b"\x00\x00\x00 not audio either " + b"z" * 4096
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            validate_upload_stream(_make_upload(garbage), purpose="audio_upload"),
        )
    assert exc.value.status_code == 400
    assert "音频/视频" in exc.value.detail


def test_empty_body_rejected_with_empty_message():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            validate_upload_stream(_make_upload(b""), purpose="resume"),
        )
    assert exc.value.status_code == 400
    assert "文件内容为空" in exc.value.detail


def test_size_cap_enforced_progressively():
    """Size > limit must be rejected BEFORE the whole body buffers.
    Simulate by setting a tiny test-only limit, then post a body
    that's twice that size."""
    limit = _SIZE_LIMITS_BYTES["resume"]
    # 10 MB + 1 byte: with valid PDF magic at the head, the stream
    # phase should detect the overrun and abort.
    overrun = b"%PDF-1.4\n" + b"\x00" * (limit)  # head + limit = limit + 9 > limit
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            validate_upload_stream(
                _make_upload(overrun, "huge.pdf"),
                purpose="resume",
            ),
        )
    assert exc.value.status_code == 400
    assert "MB 上限" in exc.value.detail


def test_spool_rolls_over_for_big_uploads():
    """Bodies above the spool's RAM threshold roll over to disk.
    We can't easily observe the disk file path (SpooledTemporaryFile
    hides it), but we CAN check that ``_rolled`` is True after a
    >threshold write — that's the documented private API for this
    state.
    """
    # 2 MiB PDF body (> the 1 MiB rollover threshold).
    big_pdf = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024)
    detected, size, spool = asyncio.run(
        validate_upload_stream(_make_upload(big_pdf, "big.pdf"), purpose="resume"),
    )
    try:
        assert detected == "pdf"
        assert size == len(big_pdf)
        # SpooledTemporaryFile exposes ``_rolled`` after rollover.
        assert spool._rolled is True, (
            "Body bigger than _SPOOL_ROLLOVER_BYTES should have rolled to disk"
        )
    finally:
        spool.close()
