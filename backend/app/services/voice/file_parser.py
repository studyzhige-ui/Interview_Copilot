"""File parsing utilities for interview analysis pipeline.

Provides:
  - extract_resume_text():  PDF / DOCX / TXT → plain text
  - validate_media_format(): audio/video extension whitelist
  - validate_resume_format(): resume extension whitelist
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Format whitelists ────────────────────────────────────────────────────

ALLOWED_MEDIA_EXTENSIONS: frozenset[str] = frozenset({
    # Audio
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".aac",
    # Video (WhisperX/ffmpeg auto-extracts audio track)
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
})

ALLOWED_RESUME_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".txt", ".md",
})


def validate_media_format(filename: str) -> bool:
    """Check if the filename has an allowed audio/video extension."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_MEDIA_EXTENSIONS


def validate_resume_format(filename: str) -> bool:
    """Check if the filename has an allowed resume extension."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_RESUME_EXTENSIONS


# ── Resume text extraction ───────────────────────────────────────────────

def extract_resume_text(file_path: str) -> str:
    """Extract plain text from a resume file.

    Supports PDF (PyMuPDF → pypdf fallback), DOCX (python-docx), TXT/MD.
    Returns the full text content as a string.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Resume file not found: {file_path}")

    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext == ".docx":
        return _extract_docx(file_path)
    elif ext in {".txt", ".md"}:
        return _extract_plain_text(file_path)
    else:
        raise ValueError(f"Unsupported resume format: {ext}")


def _extract_pdf(file_path: str) -> str:
    """Extract text from PDF using PyMuPDF, with pypdf fallback."""
    # Primary: PyMuPDF (already in requirements as pymupdf)
    try:
        import fitz  # pymupdf

        doc = fitz.open(file_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        text = "\n\n".join(pages).strip()
        if text:
            logger.info("PDF extracted via PyMuPDF: %d chars", len(text))
            return text
    except Exception as exc:
        logger.warning("PyMuPDF extraction failed, trying pypdf: %s", exc)

    # Fallback: pypdf (also in requirements)
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages).strip()
        logger.info("PDF extracted via pypdf: %d chars", len(text))
        return text
    except Exception as exc:
        logger.error("Both PDF extractors failed: %s", exc)
        raise


def _extract_docx(file_path: str) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        from docx import Document

        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n\n".join(paragraphs).strip()
        logger.info("DOCX extracted: %d chars", len(text))
        return text
    except ImportError:
        raise ImportError(
            "python-docx is required for DOCX parsing. "
            "Install it with: pip install python-docx"
        )


def _extract_plain_text(file_path: str) -> str:
    """Read plain text file as UTF-8."""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    logger.info("Plain text extracted: %d chars", len(text))
    return text


__all__ = [
    "extract_resume_text",
    "validate_media_format",
    "validate_resume_format",
    "ALLOWED_MEDIA_EXTENSIONS",
    "ALLOWED_RESUME_EXTENSIONS",
]
