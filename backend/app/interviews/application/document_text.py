"""Extract plain text from interview resume and JD documents."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_document_text(file_path: str) -> str:
    """Extract plain text from a resume or job-description file.

    Supports PDF (PyMuPDF → pypdf fallback), DOCX (python-docx), TXT/MD.
    Returns the full text content as a string.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext == ".docx":
        return _extract_docx(file_path)
    elif ext in {".txt", ".md"}:
        return _extract_plain_text(file_path)
    else:
        raise ValueError(f"Unsupported document format: {ext}")


def _extract_pdf(file_path: str) -> str:
    """Extract text from a PDF, preserving visual reading order where possible.

    Three-layer ladder, best → worst layout fidelity:

    1. **LlamaParse** (cloud)  — when ``LLAMA_CLOUD_API_KEY`` is set we use
       the same parser already wired up for RAG ingestion. It produces
       markdown that honors the visual layout (multi-column resumes,
       sidebars, tables) much better than rule-based extractors. This is
       the path that prevents the "项目经历 / 教育背景 / 日期" sections
       from getting shuffled when the PDF has a two-column layout — the
       failure mode that produced confusing analysis output before this
       change.

    2. **PyMuPDF with ``sort=True``** — local fallback. Without ``sort=True``
       PyMuPDF returns text blocks in raw stream order, which on a
       two-column resume tends to interleave the left and right columns
       and scramble dates / section headers. ``sort=True`` re-orders by
       (y, x) top-left coordinate so blocks come out in human reading
       order. This is the single most important PyMuPDF flag for resume
       parsing.

    3. **pypdf** — last resort if both above fail. Layout fidelity is
       roughly the same as unsorted PyMuPDF; we keep it as a safety net.
    """
    # ── Layer 1: LlamaParse (markdown, layout-aware) ──────────────────
    try:
        from app.core.config import settings

        api_key = (settings.LLAMA_CLOUD_API_KEY or "").strip()
        if api_key and not api_key.startswith("your_"):
            import nest_asyncio

            nest_asyncio.apply()
            from llama_parse import LlamaParse

            parser = LlamaParse(
                result_type="markdown",
                language="ch_sim",
                api_key=api_key,
                num_workers=1,
            )
            docs = parser.load_data(file_path)
            text = "\n\n".join((d.text or "").strip() for d in docs).strip()
            if text:
                logger.info("PDF extracted via LlamaParse: %d chars", len(text))
                return text
            logger.warning("LlamaParse returned empty text; falling back to PyMuPDF.")
    except Exception as exc:  # noqa: BLE001 — any LlamaParse failure → fall back
        logger.warning("LlamaParse extraction failed, falling back to PyMuPDF: %s", exc)

    # ── Layer 2: PyMuPDF with sort=True ───────────────────────────────
    try:
        import fitz  # pymupdf

        doc = fitz.open(file_path)
        # ``sort=True`` re-orders text blocks by visual position before
        # serialization — critical for multi-column resumes.
        pages = [page.get_text("text", sort=True) for page in doc]
        doc.close()
        text = "\n\n".join(pages).strip()
        if text:
            logger.info("PDF extracted via PyMuPDF (sorted): %d chars", len(text))
            return text
    except Exception as exc:
        logger.warning("PyMuPDF extraction failed, trying pypdf: %s", exc)

    # ── Layer 3: pypdf ────────────────────────────────────────────────
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(pages).strip()
        logger.info("PDF extracted via pypdf: %d chars", len(text))
        return text
    except Exception as exc:
        logger.error("All PDF extractors failed: %s", exc)
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
    "extract_document_text",
]
