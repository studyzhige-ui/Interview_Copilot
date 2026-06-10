"""Business whitelist for knowledge-document upload formats (ingestion §4.1.2).

Knowledge-doc bytes go straight to object storage via a presigned URL — they
never traverse the API — so this is an EXTENSION-level business gate, not a
magic-byte check (that's ``file_validation.py``, for streamed uploads). It is
the scope/security boundary: a parser being *able* to read a format doesn't
make it business-allowed.

Enforced at ``POST /knowledge/documents`` (authoritative) and re-checked
defensively in the worker before ingest. The frontend ``accept`` is UX only.
"""
from __future__ import annotations

import os

# Formats whose parser works TODAY. (json + code files are supported by the
# current get_optimal_nodes splitters, so they stay in.)
ALLOWED_KNOWLEDGE_EXTENSIONS = frozenset({
    ".pdf",
    ".docx", ".pptx", ".xlsx",
    ".html", ".htm", ".md", ".markdown", ".txt",
    ".csv", ".tsv",
    ".json",
    ".py", ".java", ".cpp", ".c",
})

# In the §4.1.2 target whitelist but pending their parser packages (images →
# OCR/Docling, legacy Office → LibreOffice), both deferred to B4+. Rejected
# now with a specific "coming later" message rather than a generic error.
DEFERRED_KNOWLEDGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp",
    ".doc", ".ppt", ".xls",
})

# Shown in the generic rejection message.
SUPPORTED_FORMATS_HINT = (
    "PDF、Word(.docx)、PPT(.pptx)、Excel(.xlsx)、Markdown、HTML、"
    "文本(.txt)、CSV/TSV、JSON、代码文件(.py/.java/.cpp/.c)"
)


class UnsupportedDocumentFormat(ValueError):
    """Friendly, user-facing rejection — ``str(exc)`` is a Chinese message
    safe to return as an HTTP 400 detail / store as a document error."""


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def validate_knowledge_document_format(
    filename: str, content_type: str | None = None,
) -> str:
    """Return the normalized extension if the format is business-allowed; else
    raise :class:`UnsupportedDocumentFormat` with a friendly Chinese message.

    The content_type check is intentionally conservative — only an obvious
    conflict (an audio/video MIME type) is rejected, since the client-declared
    type is often a generic ``application/octet-stream``.
    """
    ext = _ext(filename)
    content_type = (content_type or "").lower()

    if content_type.startswith(("audio/", "video/")):
        raise UnsupportedDocumentFormat("知识库不支持音视频文件，请上传文档类文件。")
    if not ext:
        raise UnsupportedDocumentFormat("无法识别文件类型，请上传带扩展名的受支持文档。")
    if ext in DEFERRED_KNOWLEDGE_EXTENSIONS:
        raise UnsupportedDocumentFormat(
            f"暂不支持 {ext} 格式（图片 OCR 与旧版 Office 即将支持）；"
            f"请转换为 {SUPPORTED_FORMATS_HINT} 等格式后上传。"
        )
    if ext not in ALLOWED_KNOWLEDGE_EXTENSIONS:
        raise UnsupportedDocumentFormat(
            f"不支持的文件格式 {ext}。支持：{SUPPORTED_FORMATS_HINT}。"
        )
    return ext


__all__ = [
    "ALLOWED_KNOWLEDGE_EXTENSIONS",
    "DEFERRED_KNOWLEDGE_EXTENSIONS",
    "SUPPORTED_FORMATS_HINT",
    "UnsupportedDocumentFormat",
    "validate_knowledge_document_format",
]
