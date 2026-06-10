"""S0 conservative text cleaning for ingestion (plan §4.2).

Only SAFE normalization — make parsed text safe to index and format-stable,
never "pretty". This deliberately does NOT remove headers/footers/ads/nav,
dedupe paragraphs, fix OCR typos, or LLM-rewrite: that kind of aggressive
cleanup routinely deletes real interview-note / Q&A content. Build quality is
left to parsing, chunking, annotation and retrieval.

``clean_text`` is a pure function returning ``(cleaned, CleaningProfile)``.
Emptiness policy is the caller's job — a single blank page shouldn't fail a
multi-page import; only a document with no usable text anywhere should
(callers raise :class:`EmptyContentError`). Quality issues are recorded as
``warnings`` and never change the text.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_BOM = "﻿"
_REPLACEMENT_CHAR = "�"
# Replacement-char ratio above this suggests a decoding/mojibake problem.
_MOJIBAKE_RATIO = 0.02
_BLANK_RUN_RE = re.compile(r"\n{3,}")


class EmptyContentError(ValueError):
    """Raised by ingest callers when a document has no usable text after S0
    cleaning. ``str(exc)`` is a friendly Chinese message safe to surface."""


@dataclass
class CleaningProfile:
    """Lightweight diagnostic from one S0 pass — logged, and persisted into a
    chunk's ``metadata_json`` (diagnostic field, plan §4.4.3) via ``as_dict``."""

    char_in: int
    char_out: int
    removed_control_chars: int = 0
    replacement_char_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "char_in": self.char_in,
            "char_out": self.char_out,
            "removed_control_chars": self.removed_control_chars,
            "replacement_char_count": self.replacement_char_count,
            "warnings": self.warnings,
        }


def _strip_control_chars(text: str) -> tuple[str, int]:
    """Drop NUL / C0-C1 control chars (keep \\n and \\t) and unpaired
    surrogates. Format chars (Cf: ZWJ, RTL marks, …) are intentionally kept —
    they can be semantically meaningful and removing them isn't "safe"."""
    out: list[str] = []
    removed = 0
    for ch in text:
        if ch in ("\n", "\t"):
            out.append(ch)
            continue
        if ch == "\x00" or unicodedata.category(ch) in ("Cc", "Cs"):
            removed += 1
            continue
        out.append(ch)
    return "".join(out), removed


def clean_text(text: str) -> tuple[str, CleaningProfile]:
    """Apply the S0 pipeline. Returns ``(cleaned_text, profile)``; never
    raises (emptiness is the caller's policy)."""
    raw = text or ""
    char_in = len(raw)
    replacement_count = raw.count(_REPLACEMENT_CHAR)

    # 1. strip a leading BOM; 2. Unicode NFC (safe compatibility folding only).
    s = unicodedata.normalize("NFC", raw.lstrip(_BOM))
    # 3. normalise newlines CRLF / CR -> LF.
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # 4. drop control chars / surrogates.
    s, removed_control = _strip_control_chars(s)
    # 5. trim trailing whitespace per line; collapse >2 blank lines to one
    #    blank line; trim leading/trailing blank lines.
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = _BLANK_RUN_RE.sub("\n\n", s).strip()

    warnings: list[str] = []
    if char_in and replacement_count / char_in > _MOJIBAKE_RATIO:
        warnings.append("mojibake_suspected")

    profile = CleaningProfile(
        char_in=char_in,
        char_out=len(s),
        removed_control_chars=removed_control,
        replacement_char_count=replacement_count,
        warnings=warnings,
    )
    return s, profile


__all__ = ["EmptyContentError", "CleaningProfile", "clean_text"]
