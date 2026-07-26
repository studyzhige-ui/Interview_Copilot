"""Tests for the knowledge-document format whitelist (ingestion §4.1.2)."""

from __future__ import annotations

import pytest

from app.services.knowledge.document_formats import (
    ALLOWED_KNOWLEDGE_EXTENSIONS,
    UnsupportedDocumentFormat,
    validate_knowledge_document_format,
)


@pytest.mark.parametrize(
    "filename",
    [
        "redis.pdf",
        "notes.docx",
        "deck.pptx",
        "data.xlsx",
        "page.html",
        "page.htm",
        "readme.md",
        "guide.markdown",
        "log.txt",
        "rows.csv",
        "rows.tsv",
        "config.json",
        "main.py",
        "App.java",
        "engine.cpp",
        "kernel.c",
        "UPPER.PDF",  # case-insensitive
    ],
)
def test_allowed_formats_pass(filename):
    ext = validate_knowledge_document_format(filename)
    assert ext in ALLOWED_KNOWLEDGE_EXTENSIONS


@pytest.mark.parametrize(
    "filename", ["scan.png", "photo.jpg", "img.jpeg", "x.tiff", "y.bmp", "z.webp"]
)
def test_image_formats_now_allowed(filename):
    """Images are OCR-ingested (Docling RapidOCR / LlamaParse cloud) as of the
    OCR round — they moved out of the deferred set into the whitelist."""
    ext = validate_knowledge_document_format(filename)
    assert ext in ALLOWED_KNOWLEDGE_EXTENSIONS


@pytest.mark.parametrize("filename", ["old.doc", "slides.ppt", "sheet.xls"])
def test_legacy_office_now_allowed(filename):
    """Legacy Office is business-allowed now (LlamaParse direct, or a server-side
    LibreOffice→OOXML conversion); the parse layer gives a friendly error if the
    server can do neither, but the whitelist no longer rejects the upload."""
    ext = validate_knowledge_document_format(filename)
    assert ext in ALLOWED_KNOWLEDGE_EXTENSIONS


@pytest.mark.parametrize(
    "filename", ["malware.exe", "archive.zip", "movie.mkv", "noext"]
)
def test_unknown_formats_rejected_generic(filename):
    with pytest.raises(UnsupportedDocumentFormat):
        validate_knowledge_document_format(filename)


def test_no_extension_rejected():
    with pytest.raises(UnsupportedDocumentFormat) as exc:
        validate_knowledge_document_format("plainname")
    assert "无法识别" in str(exc.value)


def test_audio_video_content_type_rejected_even_with_ok_ext():
    """An obvious content_type conflict (AV) is rejected regardless of ext."""
    with pytest.raises(UnsupportedDocumentFormat) as exc:
        validate_knowledge_document_format("track.pdf", content_type="audio/mpeg")
    assert "音视频" in str(exc.value)


def test_generic_octet_stream_content_type_is_allowed():
    """The common generic content_type must NOT trigger a false rejection."""
    ext = validate_knowledge_document_format(
        "redis.pdf", content_type="application/octet-stream"
    )
    assert ext == ".pdf"


def test_content_type_does_not_rescue_unsupported_extension():
    """content_type only REJECTS (AV) — it never RESCUES: an unsupported ext
    is still rejected even with a benign content_type."""
    with pytest.raises(UnsupportedDocumentFormat):
        validate_knowledge_document_format("malware.exe", content_type="text/plain")
