"""Parser selection + orchestration (plan §4.1.1/§4.1.3).

The ingest pipeline calls :func:`parse_document`; this module owns which parsers
to try and in what order, tries them until one yields usable text, and records
which parser actually ran (the ``parser_profile`` observability). E1 reproduces
the previous key-based selection (LlamaParse when a LlamaCloud key is set, else
PyMuPDF/default reader) — Docling (E2) and the per-format lightweight matrix
(E3) extend ``_candidates`` without touching callers.
"""
from __future__ import annotations

import logging
import os
import time

from app.core.config import settings

from .base import ParseResult
from .parsers import (
    DoclingParser,
    DocxParser,
    HtmlParser,
    LlamaParseParser,
    PptxParser,
    PyMuPDFParser,
    SimpleReaderParser,
    TextParser,
    XlsxParser,
)

logger = logging.getLogger(__name__)

_docling_available_cache: bool | None = None

# Per-format lightweight parser (plan §4.1.3) — the controlled fallback after the
# first-class tier. Formats not listed fall to SimpleReader (json / md / unknown).
_LIGHTWEIGHT: dict[str, type] = {
    ".pdf": PyMuPDFParser,
    ".docx": DocxParser,
    ".pptx": PptxParser,
    ".xlsx": XlsxParser,
    ".html": HtmlParser,
    ".htm": HtmlParser,
    ".txt": TextParser,
    ".csv": TextParser,
    ".tsv": TextParser,
}


def _lightweight_for(ext: str):
    cls = _LIGHTWEIGHT.get(ext)
    return cls() if cls is not None else None


def _has_llama_cloud() -> bool:
    key = settings.LLAMA_CLOUD_API_KEY
    return bool(key and key.strip() and not key.startswith("your_"))


def _docling_available() -> bool:
    """Whether the Docling package is importable (cached). The registry skips
    Docling when it isn't, so a deployment without it degrades gracefully."""
    global _docling_available_cache
    if _docling_available_cache is None:
        try:
            import docling.document_converter  # noqa: F401
            _docling_available_cache = True
        except Exception:  # noqa: BLE001 — any import/init issue -> treat as unavailable
            _docling_available_cache = False
    return _docling_available_cache


def _first_class_parsers() -> dict:
    """Available first-class parsers by id, gated on key (LlamaParse) /
    installability (Docling) — peers, deployment config picks the primary."""
    out: dict = {}
    if _has_llama_cloud():
        out["llamaparse"] = LlamaParseParser()
    if _docling_available():
        out["docling"] = DoclingParser()
    return out


def _candidates(ext: str) -> list:
    """Ordered parser candidates for an extension: the PARSER_PROVIDER-selected
    first-class parser first, then the OTHER first-class as document-level
    fallback, then per-format lightweight, then the default reader. Any tier
    being unavailable simply drops out — the list is never empty (SimpleReader
    is the floor)."""
    first_class = _first_class_parsers()
    primary_id = (settings.PARSER_PROVIDER or "docling").strip().lower()
    if primary_id not in ("docling", "llamaparse"):
        logger.warning(
            "unknown PARSER_PROVIDER=%r; using insertion order for first-class parsers",
            primary_id,
        )

    ordered: list = []
    if primary_id in first_class:
        ordered.append(first_class.pop(primary_id))
    ordered.extend(first_class.values())  # the remaining first-class as fallback

    out = [p for p in ordered if p.supports(ext)]
    lightweight = _lightweight_for(ext)
    if lightweight is not None:
        out.append(lightweight)
    out.append(SimpleReaderParser())  # default reader + final fallback
    return out


def parse_document(file_path: str) -> ParseResult:
    """Parse a file into one :class:`ParseResult`, trying candidates in order
    until one yields non-empty text. Stamps ``parser_profile`` (tier /
    fallback_used / page_count / char_count / duration_ms / warnings). Raises
    :class:`EmptyContentError` (permanent, friendly) if every candidate fails or
    yields nothing — the worker surfaces it without a pointless retry."""
    from app.rag.cleaning import EmptyContentError

    ext = os.path.splitext(file_path)[1].lower()
    candidates = _candidates(ext)
    warnings: list[str] = []
    t0 = time.perf_counter()

    for idx, parser in enumerate(candidates):
        try:
            result = parser.parse(file_path)
        except Exception as exc:  # noqa: BLE001 — record + try the next candidate
            logger.warning("parser %s failed on %s: %s", parser.id, file_path, exc)
            warnings.append(f"{parser.id}: {exc}")
            continue
        if not result.markdown.strip():
            warnings.append(f"{parser.id}: empty output")
            continue
        # Merge this parser's own warnings (its channel) with the cross-attempt
        # failure/empty warnings; warnings live inside the owning profile, never
        # as a separate top-level key.
        merged = warnings + list(result.warnings)
        result.parser_profile = {
            "tier": parser.tier,
            "fallback_used": idx > 0,
            "page_count": len(result.page_map),
            "char_count": len(result.markdown),
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
        if merged:
            result.parser_profile["warnings"] = merged
        logger.info("parsed %s via %s (fallback=%s)", file_path, parser.id, idx > 0)
        return result

    raise EmptyContentError("文档解析失败或内容为空，请确认文件完整且为受支持的格式。")
