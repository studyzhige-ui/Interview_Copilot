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
from .parsers import LlamaParseParser, PyMuPDFParser, SimpleReaderParser

logger = logging.getLogger(__name__)


def _has_llama_cloud() -> bool:
    key = settings.LLAMA_CLOUD_API_KEY
    return bool(key and key.strip() and not key.startswith("your_"))


def _candidates(ext: str) -> list:
    """Ordered parser candidates for an extension (E1): first-class LlamaParse
    (when a key is set) -> per-format lightweight -> default reader. Returning a
    list (not a single parser) is what gives document-level fallback."""
    out: list = []
    if _has_llama_cloud():
        llama = LlamaParseParser()
        if llama.supports(ext):
            out.append(llama)
    if ext == ".pdf":
        out.append(PyMuPDFParser())
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
        result.warnings = warnings
        result.parser_profile = {
            "tier": parser.tier,
            "fallback_used": idx > 0,
            "page_count": len(result.page_map),
            "char_count": len(result.markdown),
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
        if warnings:
            result.parser_profile["warnings"] = warnings
        logger.info("parsed %s via %s (fallback=%s)", file_path, parser.id, idx > 0)
        return result

    raise EmptyContentError("文档解析失败或内容为空，请确认文件完整且为受支持的格式。")
