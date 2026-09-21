"""Lossless text layout and conservative, time-anchored overlap seams.

A seam requires the same lexical word at overlapping acoustic times on both
sides, or silence on both sides. Repeated words at different times are not
collapsed. No fuzzy text deduplication, invented timing, or partial success.
"""

from __future__ import annotations

from app.local_inference.audio import _lexical

MAX_BOUNDARY_WORDS = 128


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
        if word["start"] is None or word["end"] is None:
            raise ValueError("longform_alignment_missing")
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
                "text": text[0 if index == 0 else start : end],
                "start": offset + word["start"],
                "end": offset + word["end"],
            }
        )
    return result


def stitch_boundary(
    left: list[dict],
    right: list[dict],
    *,
    boundary: float,
    overlap_start: float,
    overlap_end: float,
) -> tuple[list[dict], list[dict]]:
    """Return finalized left words and a still-provisional right suffix."""
    candidates = []
    for words in (left, right):
        near = [
            (i, word, _lexical(word["text"]))
            for i, word in enumerate(words)
            if word["start"] < overlap_end and word["end"] > overlap_start
        ]
        if len(near) > MAX_BOUNDARY_WORDS:
            raise ValueError("longform_boundary_capacity")
        candidates.append(near)
    a, b = candidates
    if not a and not b:
        return (
            [word for word in left if word["end"] <= boundary],
            [word for word in right if word["start"] >= boundary],
        )
    pairs = [
        (i, j)
        for i, word, key in a
        for j, other, other_key in b
        if key
        and key == other_key
        and max(word["start"], other["start"]) < min(word["end"], other["end"])
    ]
    left_counts: dict[int, int] = {}
    right_counts: dict[int, int] = {}
    for i, j in pairs:
        left_counts[i] = left_counts.get(i, 0) + 1
        right_counts[j] = right_counts.get(j, 0) + 1
    unique = sorted(
        (i, j) for i, j in pairs if left_counts[i] == right_counts[j] == 1
    )
    if not unique or any(
        second[1] <= first[1] for first, second in zip(unique, unique[1:])
    ):
        raise ValueError("longform_boundary_ambiguous")
    i, j = min(
        unique,
        key=lambda pair: (
            abs((left[pair[0]]["start"] + left[pair[0]]["end"]) / 2 - boundary),
            pair,
        ),
    )
    # Keep the right copy of the anchor so its following punctuation/spacing
    # remains attached to the right-hand continuation ("Hello" + "world"
    # must not become "Helloworld" at a seam).
    finalized, pending = left[:i], right[j:]
    if finalized and pending and pending[0]["start"] < finalized[-1]["start"]:
        raise ValueError("longform_boundary_time_reversed")
    return finalized, pending
