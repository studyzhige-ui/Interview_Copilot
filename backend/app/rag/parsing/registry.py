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
import shutil
import subprocess
import tempfile
import time

from app.core.config import settings
from app.core.runtime_files import runtime_temp_dir

from .base import (
    IMAGE_EXTS,
    LEGACY_OFFICE_EXTS,
    LEGACY_OFFICE_TARGET,
    DocumentParser,
    ParseResult,
)
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


def _lightweight_for(ext: str) -> DocumentParser | None:
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
            from app.core.hf_runtime import prepare_hf_runtime

            prepare_hf_runtime()
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
    primary_id = (settings.PARSER_PROVIDER or "lightweight").strip().lower()
    if primary_id not in ("docling", "llamaparse", "lightweight"):
        logger.warning(
            "unknown PARSER_PROVIDER=%r; using insertion order for first-class parsers",
            primary_id,
        )

    ordered: list = []
    if primary_id in first_class:
        ordered.append(first_class.pop(primary_id))
    ordered.extend(first_class.values())  # the remaining first-class as fallback

    lightweight = _lightweight_for(ext)
    out = [p for p in ordered if p.supports(ext)]
    if lightweight is not None:
        if primary_id == "lightweight":
            out.insert(0, lightweight)
        else:
            out.append(lightweight)
    # Binary formats (images + legacy Office) get NO SimpleReader text catch-all
    # (§4.1.3 matrix: no lightweight fallback): SimpleDirectoryReader reads an
    # unmapped binary (.tiff/.bmp/.doc/.xls) as raw bytes → garbage that passes
    # the emptiness gate and gets indexed. For them the list is first-class-only;
    # with none available it's empty → the caller raises the friendly error.
    if ext not in IMAGE_EXTS and ext not in LEGACY_OFFICE_EXTS:
        out.append(SimpleReaderParser())  # default reader + final fallback
    return out


def _run_candidates(
    file_path: str,
    candidates: list,
    *,
    legacy_conversion_used: bool = False,
) -> ParseResult | None:
    """Try candidates in order; return the first non-empty ParseResult with its
    ``parser_profile`` stamped, or None if every candidate fails / yields empty.
    Never raises — the caller decides the friendly final error message."""
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
        if legacy_conversion_used:  # §4.1.4 rule 8 observability
            result.parser_profile["legacy_conversion_used"] = True
        if merged:
            result.parser_profile["warnings"] = merged
        logger.info("parsed %s via %s (fallback=%s)", file_path, parser.id, idx > 0)
        return result
    return None


def _soffice_convert(
    soffice: str, file_path: str, target_ext: str, outdir: str
) -> str | None:
    """Convert a legacy Office file to modern OOXML via headless LibreOffice,
    returning the converted path under ``outdir`` (or None if no output landed).
    Raises on a non-zero exit / timeout — the caller treats that as conversion
    failure. ``--convert-to`` wants the bare filter name ("docx", not ".docx")."""
    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            target_ext.lstrip("."),
            "--outdir",
            outdir,
            file_path,
        ],
        capture_output=True,
        timeout=180,
        check=True,
    )
    base = os.path.splitext(os.path.basename(file_path))[0]
    converted = os.path.join(outdir, f"{base}{target_ext}")
    if not os.path.exists(converted):
        logger.warning("soffice produced no output for %s: %s", file_path, proc.stdout)
        return None
    return converted


def _parse_legacy_office(file_path: str, ext: str) -> ParseResult:
    """Legacy .doc/.ppt/.xls (plan §4.1.3): LlamaParse parses them directly when
    available; otherwise convert to modern OOXML via LibreOffice/headless soffice
    and run the normal candidates on the converted file (so .xls→.xlsx still uses
    openpyxl, .doc→.docx uses Docling/python-docx, etc.). soffice absent AND no
    LlamaParse → a friendly error: install LibreOffice, switch to OOXML, or
    configure LlamaParse (§4.1.4 rule 5)."""
    from app.rag.cleaning import EmptyContentError

    # 1. First-class direct: _candidates(ext) is [LlamaParse] when a key is set
    #    (Docling doesn't claim legacy office); binaries get no text catch-all.
    result = _run_candidates(file_path, _candidates(ext))
    if result is not None:
        return result

    # 2. LibreOffice conversion → modern OOXML → the modern format's candidates.
    target_ext = LEGACY_OFFICE_TARGET[ext]
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory(dir=runtime_temp_dir()) as outdir:
            try:
                converted = _soffice_convert(soffice, file_path, target_ext, outdir)
            except Exception as exc:  # noqa: BLE001 — fall through to the friendly error
                logger.warning(
                    "LibreOffice conversion failed for %s: %s", file_path, exc
                )
                converted = None
            if converted is not None:
                # markdown is read into memory before the tempdir is cleaned up.
                result = _run_candidates(
                    converted,
                    _candidates(target_ext),
                    legacy_conversion_used=True,
                )
                if result is not None:
                    return result

    raise EmptyContentError(
        f"旧版 Office 文档（{ext}）解析失败：请在服务器安装 LibreOffice，"
        f"或将文件转换为 {target_ext} 后重新上传，或配置 LlamaParse 云端解析。"
    )


def parse_document(file_path: str) -> ParseResult:
    """Parse a file into one :class:`ParseResult`, trying candidates in order
    until one yields non-empty text. Stamps ``parser_profile`` (tier /
    fallback_used / page_count / char_count / duration_ms / warnings; plus
    legacy_conversion_used on the LibreOffice path). Raises
    :class:`EmptyContentError` (permanent, friendly) if every candidate fails or
    yields nothing — the worker surfaces it without a pointless retry."""
    from app.rag.cleaning import EmptyContentError

    ext = os.path.splitext(file_path)[1].lower()
    if ext in LEGACY_OFFICE_EXTS:
        return _parse_legacy_office(file_path, ext)

    result = _run_candidates(file_path, _candidates(ext))
    if result is not None:
        return result
    raise EmptyContentError("文档解析失败或内容为空，请确认文件完整且为受支持的格式。")
