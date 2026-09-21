"""Indexed speaker coverage, distinct from simultaneous-speech evidence.

Build once for a recording. Primary identity uses exclusive-track coverage;
overlap requires positive-duration coexistence of *different* speakers in the
regular track. Merely crossing an adjacent turn boundary is not overlap.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol


class SpeakerInterval(Protocol):
    """Read-only observations needed by the index, independent of wire schemas."""

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def speaker_id(self) -> str: ...


class SpeakerTimeline:
    """Read-only indexes over validated diarization observations.

    Exclusive tracks are non-overlapping at the composition boundary. Lookup
    then costs O(log N + intersecting intervals), not a full-recording scan for
    every word. Regular-track overlap regions are swept once in O(N log N).
    Original tracks are not changed, merged or replaced in persisted evidence.
    """

    def __init__(
        self,
        regular: Sequence[SpeakerInterval],
        exclusive: Sequence[SpeakerInterval],
    ) -> None:
        self._exclusive = sorted(exclusive, key=lambda row: row.start)
        self._starts = [row.start for row in self._exclusive]
        self._prefix_ends: list[float] = []
        furthest = 0.0
        for row in self._exclusive:
            furthest = max(furthest, row.end)
            self._prefix_ends.append(furthest)

        events: dict[float, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in regular:
            events[row.start][row.speaker_id] += 1
            events[row.end][row.speaker_id] -= 1
        self._overlap_starts: list[float] = []
        self._overlap_ends: list[float] = []
        active: dict[str, int] = {}
        previous: float | None = None
        for time in sorted(events):
            if previous is not None and previous < time and len(active) > 1:
                if self._overlap_ends and self._overlap_ends[-1] == previous:
                    self._overlap_ends[-1] = time
                else:
                    self._overlap_starts.append(previous)
                    self._overlap_ends.append(time)
            # Process all starts/ends at one instant together. Duplicate or
            # nested intervals of one speaker still count as only one voice.
            for speaker, delta in events[time].items():
                count = active.get(speaker, 0) + delta
                if count:
                    active[speaker] = count
                else:
                    active.pop(speaker, None)
            previous = time

    def assign(self, start: float, end: float) -> tuple[str | None, float | None, bool]:
        stop = bisect_left(self._starts, end)
        first = bisect_right(self._prefix_ends, start, 0, stop)
        scores: dict[str, float] = {}
        for index in range(first, stop):
            row = self._exclusive[index]
            amount = max(0.0, min(end, row.end) - max(start, row.start))
            if amount:
                scores[row.speaker_id] = scores.get(row.speaker_id, 0.0) + amount
        if scores:
            speaker, amount = max(scores.items(), key=lambda item: item[1])
            confidence: float | None = min(1.0, amount / max(end - start, 1e-6))
        else:
            speaker, confidence = None, None
        region = bisect_right(self._overlap_ends, start)
        overlap = (
            region < len(self._overlap_starts) and self._overlap_starts[region] < end
        )
        return speaker, confidence, overlap
