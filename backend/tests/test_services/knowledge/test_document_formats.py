"""Tests for the knowledge-document format whitelist (ingestion §4.1.2)."""

from __future__ import annotations

import pytest
from app.rag.application.library.document_formats import ALLOWED_KNOWLEDGE_EXTENSIONS
from app.rag.application.library.document_formats import UnsupportedDocumentFormat
from app.rag.application.library.document_formats import (
    validate_knowledge_document_format,
)


def test_supported_format_matrix_returns_exact_normalized_extensions():
    # Upload eligibility is independent of which local parser is available.
    # Retain every former document/image/legacy-office/case-folding input.
    expected = {
        "redis.pdf": ".pdf",
        "notes.docx": ".docx",
        "deck.pptx": ".pptx",
        "data.xlsx": ".xlsx",
        "page.html": ".html",
        "page.htm": ".htm",
        "readme.md": ".md",
        "guide.markdown": ".markdown",
        "log.txt": ".txt",
        "rows.csv": ".csv",
        "rows.tsv": ".tsv",
        "config.json": ".json",
        "main.py": ".py",
        "App.java": ".java",
        "engine.cpp": ".cpp",
        "kernel.c": ".c",
        "UPPER.PDF": ".pdf",
        "scan.png": ".png",
        "photo.jpg": ".jpg",
        "img.jpeg": ".jpeg",
        "x.tiff": ".tiff",
        "y.bmp": ".bmp",
        "z.webp": ".webp",
        "old.doc": ".doc",
        "slides.ppt": ".ppt",
        "sheet.xls": ".xls",
    }
    assert set(expected.values()) == ALLOWED_KNOWLEDGE_EXTENSIONS
    assert {
        filename: validate_knowledge_document_format(filename) for filename in expected
    } == expected


@pytest.mark.parametrize("filename", ["malware.exe", "archive.zip", "movie.mkv"])
def test_unknown_formats_rejected_generic(filename):
    with pytest.raises(UnsupportedDocumentFormat):
        validate_knowledge_document_format(filename)


def test_no_extension_rejected():
    for filename in ("noext", "plainname"):
        with pytest.raises(UnsupportedDocumentFormat) as exc:
            validate_knowledge_document_format(filename)
        assert "无法识别" in str(exc.value), filename


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
