"""Preserve original ASR layout while attaching forced-alignment observations."""

from __future__ import annotations

import unicodedata


def _lexical(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text)
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    )


def restore_word_layout(text: str, words: list[dict], offset: float) -> list[dict]:
    """Attach original ASR punctuation/spacing to timed lexical observations."""
    lexical = []
    positions = []
    for index, char in enumerate(text):
        value = _lexical(char)
        lexical.extend(value)
        positions.extend([index] * len(value))
    # Context-sensitive Unicode normalization cannot safely be split into
    # original characters. Reject rather than silently rewriting the text.
    if "".join(lexical) != _lexical(text):
        raise ValueError("alignment_unicode_layout_ambiguous")
    selected = []
    cursor = 0
    for word in words:
        key = _lexical(word["text"])
        if not key:
            continue  # Original punctuation is retained in the source slices.
        if "".join(lexical[cursor : cursor + len(key)]) != key:
            raise ValueError("alignment_text_coverage_mismatch")
        start = positions[cursor]
        if selected and start <= selected[-1][0]:
            raise ValueError("alignment_unicode_layout_ambiguous")
        selected.append((start, word))
        cursor += len(key)
    if cursor != len(lexical) or (text.strip() and not selected):
        raise ValueError("alignment_text_coverage_mismatch")
    result = []
    for index, (start, word) in enumerate(selected):
        end = selected[index + 1][0] if index + 1 < len(selected) else len(text)
        result.append(
            {
                **word,
                "text": text[0 if index == 0 else start : end],
                "start": offset + word["start"] if word["start"] is not None else None,
                "end": offset + word["end"] if word["end"] is not None else None,
            }
        )
    return result
