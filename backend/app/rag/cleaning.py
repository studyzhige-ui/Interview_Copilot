"""Format-independent document normalization and quality diagnostics."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.rag.documents import CanonicalDocument, PageSpan, ParsedDocument

_BOM = "﻿"
_REPLACEMENT_CHAR = "�"
_MOJIBAKE_RATIO = 0.02
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_DIGITS_RE = re.compile(r"\d+")


class EmptyContentError(ValueError):
    """The document contains no safe, indexable text."""


@dataclass
class CleaningProfile:
    char_in: int
    char_out: int
    removed_control_chars: int = 0
    replacement_char_count: int = 0
    removed_repeated_edges: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "char_in": self.char_in,
            "char_out": self.char_out,
            "removed_control_chars": self.removed_control_chars,
            "replacement_char_count": self.replacement_char_count,
            "removed_repeated_edges": self.removed_repeated_edges,
            "warnings": self.warnings,
        }


def _strip_control_chars(text: str) -> tuple[str, int]:
    out: list[str] = []
    removed = 0
    for char in text:
        if char in ("\n", "\t"):
            out.append(char)
        elif char == "\x00" or unicodedata.category(char) in ("Cc", "Cs"):
            removed += 1
        else:
            out.append(char)
    return "".join(out), removed


def clean_text(text: str) -> tuple[str, CleaningProfile]:
    """Apply safe Unicode, newline, control-character, and whitespace cleanup."""
    raw = text or ""
    normalized = unicodedata.normalize("NFC", raw.lstrip(_BOM))
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized, removed_control = _strip_control_chars(normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = _BLANK_RUN_RE.sub("\n\n", normalized).strip()

    replacement_count = raw.count(_REPLACEMENT_CHAR)
    warnings: list[str] = []
    if raw and replacement_count / len(raw) > _MOJIBAKE_RATIO:
        warnings.append("mojibake_suspected")
    return normalized, CleaningProfile(
        char_in=len(raw),
        char_out=len(normalized),
        removed_control_chars=removed_control,
        replacement_char_count=replacement_count,
        warnings=warnings,
    )


def _edge_key(line: str) -> str:
    value = " ".join(line.casefold().split())
    return _DIGITS_RE.sub("#", value)


def _repeated_edge_keys(pages: list[str]) -> set[str]:
    """Find page furniture by repetition at page edges, never by document name."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        lines = [line for line in page.splitlines() if line.strip()]
        for line in [*lines[:2], *lines[-2:]]:
            key = _edge_key(line)
            if key:
                counts[key] += 1
    required = max(3, math.ceil(len(pages) * 0.6))
    return {key for key, count in counts.items() if count >= required}


def _remove_repeated_edges(text: str, repeated: set[str]) -> tuple[str, int]:
    if not repeated:
        return text, 0
    lines = text.splitlines()
    nonblank = [index for index, line in enumerate(lines) if line.strip()]
    edge_indexes = set(nonblank[:2] + nonblank[-2:])
    removed = 0
    kept: list[str] = []
    for index, line in enumerate(lines):
        if index in edge_indexes and _edge_key(line) in repeated:
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept).strip(), removed


def canonicalize_document(
    parsed: ParsedDocument,
    *,
    parser_profile: dict,
) -> CanonicalDocument:
    """Normalize one parser result into the sole chunking input contract."""
    cleaned_pages: list[str] = []
    page_numbers: list[int | None] = []
    profile = CleaningProfile(char_in=0, char_out=0)
    for page in parsed.pages:
        cleaned, page_profile = clean_text(page.text)
        profile.char_in += page_profile.char_in
        profile.removed_control_chars += page_profile.removed_control_chars
        profile.replacement_char_count += page_profile.replacement_char_count
        profile.warnings.extend(page_profile.warnings)
        if cleaned:
            cleaned_pages.append(cleaned)
            page_numbers.append(page.number)

    repeated = _repeated_edge_keys(cleaned_pages)
    normalized_pages: list[tuple[str, int | None]] = []
    for page, page_number in zip(cleaned_pages, page_numbers):
        normalized, removed = _remove_repeated_edges(page, repeated)
        profile.removed_repeated_edges += removed
        if normalized:
            normalized_pages.append((normalized, page_number))

    if not normalized_pages:
        raise EmptyContentError(
            "文档解析和清洗后没有可用文本，请确认文件完整且内容可读。"
        )

    spans: list[PageSpan] = []
    parts: list[str] = []
    cursor = 0
    for text, page_number in normalized_pages:
        if parts:
            cursor += 2
        parts.append(text)
        if page_number is not None:
            spans.append(
                PageSpan(
                    page=page_number,
                    char_start=cursor,
                    char_end=cursor + len(text),
                )
            )
        cursor += len(text)

    output = "\n\n".join(parts)
    profile.char_out = len(output)
    profile.warnings = list(dict.fromkeys([*parsed.warnings, *profile.warnings]))
    parser_profile = {
        **parser_profile,
        "page_count": len(parsed.pages),
        "char_count": len(output),
    }
    return CanonicalDocument(
        text=output,
        content_kind=parsed.content_kind,
        page_spans=spans,
        parser_id=parsed.parser_id,
        parser_profile=parser_profile,
        cleaning_profile=profile.as_dict(),
        ocr_used=parsed.ocr_used,
    )


__all__ = [
    "CleaningProfile",
    "EmptyContentError",
    "canonicalize_document",
    "clean_text",
]
