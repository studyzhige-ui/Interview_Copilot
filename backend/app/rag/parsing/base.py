"""Parser plugin contract and supported binary format groups."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.rag.documents import ParsedDocument

TIER_FIRST_CLASS = "first_class"
TIER_LIGHTWEIGHT = "lightweight"

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"})
LEGACY_OFFICE_EXTS = frozenset({".doc", ".ppt", ".xls"})
LEGACY_OFFICE_TARGET = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}


@runtime_checkable
class DocumentParser(Protocol):
    id: str
    tier: str

    def supports(self, extension: str) -> bool: ...

    def parse(self, file_path: str) -> ParsedDocument: ...


__all__ = [
    "DocumentParser",
    "IMAGE_EXTS",
    "LEGACY_OFFICE_EXTS",
    "LEGACY_OFFICE_TARGET",
    "TIER_FIRST_CLASS",
    "TIER_LIGHTWEIGHT",
]
