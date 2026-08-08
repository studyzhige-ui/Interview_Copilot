"""Parser selection and canonical-document orchestration.

The ingest pipeline calls :func:`parse_document`; this module owns which parsers
to try and in what order, tries them until one yields usable text, and records
which parser actually ran in ``parser_profile``.
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
from app.rag.cleaning import EmptyContentError, canonicalize_document
from app.rag.documents import CanonicalDocument

from .base import (
    LEGACY_OFFICE_EXTS,
    LEGACY_OFFICE_TARGET,
    DocumentParser,
)
from .parsers import (
    DoclingParser,
    DocxParser,
    HtmlParser,
    LlamaParseParser,
    PptxParser,
    PyMuPDFParser,
    TextParser,
    XlsxParser,
)

logger = logging.getLogger(__name__)

_docling_available_cache: bool | None = None

# Controlled local fallback after the configured first-class parser.
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
    ".md": TextParser,
    ".markdown": TextParser,
    ".json": TextParser,
    ".py": TextParser,
    ".java": TextParser,
    ".cpp": TextParser,
    ".c": TextParser,
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


def _candidates(ext: str) -> list:
    """Return the configured primary followed by one format-specific fallback."""
    primary_id = (settings.PARSER_PROVIDER or "docling").strip().lower()
    if primary_id not in ("docling", "llamaparse", "lightweight"):
        logger.warning(
            "unknown PARSER_PROVIDER=%r; using docling",
            primary_id,
        )
        primary_id = "docling"

    ordered: list = []
    if primary_id == "llamaparse":
        if _has_llama_cloud():
            ordered.append(LlamaParseParser())
        if _docling_available():
            ordered.append(DoclingParser())
    elif primary_id == "docling" and _docling_available():
        ordered.append(DoclingParser())

    lightweight = _lightweight_for(ext)
    out = [p for p in ordered if p.supports(ext)]
    if lightweight is not None:
        out.append(lightweight)
    return out


def _run_candidates(
    file_path: str,
    candidates: list,
    *,
    legacy_conversion_used: bool = False,
) -> CanonicalDocument | None:
    """Try candidates in order; return the first canonical document with its
    ``parser_profile`` stamped, or None if every candidate fails / yields empty.
    Never raises — the caller decides the friendly final error message."""
    warnings: list[str] = []
    t0 = time.perf_counter()
    for idx, parser in enumerate(candidates):
        try:
            parsed = parser.parse(file_path)
            parser_profile = {
                "tier": parser.tier,
                "fallback_used": idx > 0,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            }
            if legacy_conversion_used:
                parser_profile["legacy_conversion_used"] = True
            canonical = canonicalize_document(
                parsed,
                parser_profile=parser_profile,
            )
        except Exception as exc:  # noqa: BLE001 — record + try the next candidate
            logger.warning("parser %s failed on %s: %s", parser.id, file_path, exc)
            warnings.append(f"{parser.id}: {exc}")
            continue
        merged = [*warnings, *canonical.cleaning_profile.get("warnings", [])]
        if merged:
            canonical.parser_profile["warnings"] = list(dict.fromkeys(merged))
        logger.info("parsed %s via %s (fallback=%s)", file_path, parser.id, idx > 0)
        return canonical
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


def _parse_legacy_office(file_path: str, ext: str) -> CanonicalDocument:
    """Legacy .doc/.ppt/.xls (plan §4.1.3): LlamaParse parses them directly when
    available; otherwise convert to modern OOXML via LibreOffice/headless soffice
    and run the normal candidates on the converted file (so .xls→.xlsx still uses
    openpyxl, .doc→.docx uses Docling/python-docx, etc.). soffice absent AND no
    LlamaParse → a friendly error: install LibreOffice, switch to OOXML, or
    configure LlamaParse (§4.1.4 rule 5)."""
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


def parse_document(file_path: str) -> CanonicalDocument:
    """Parse and normalize a supported file into the sole ingestion contract."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in LEGACY_OFFICE_EXTS:
        return _parse_legacy_office(file_path, ext)

    result = _run_candidates(file_path, _candidates(ext))
    if result is not None:
        return result
    raise EmptyContentError("文档解析失败或内容为空，请确认文件完整且为受支持的格式。")
