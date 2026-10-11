"""Conservative recording-local acoustic identity, never a person's identity.

Centroids are fixed at first observation: repeated borderline matches cannot
move an identity through a chain of unrelated voices. Thresholds are explicit
policy inputs, not calibrated probabilities. Ambiguity rejects publication;
no acoustic vector is included in the returned identity map or durable graph.
"""

from __future__ import annotations

import math


class SpeakerIdentity:
    def __init__(
        self,
        *,
        match_threshold: float = 0.8,
        new_threshold: float = 0.5,
        margin: float = 0.1,
        max_speakers: int = 32,
    ):
        if (
            any(
                type(x) not in (int, float) or not math.isfinite(x)
                for x in (match_threshold, new_threshold, margin)
            )
            or not -1 <= new_threshold < match_threshold <= 1
            or not 0 < margin <= 2
            or type(max_speakers) is not int
            or not 1 <= max_speakers <= 32
        ):
            raise ValueError("invalid_speaker_identity_policy")
        self.match_threshold = match_threshold
        self.new_threshold = new_threshold
        self.margin = margin
        self.max_speakers = max_speakers
        self._anchors: list[tuple[float, ...]] = []
        self._dimension: int | None = None

    def assign(self, observations: list[dict]) -> dict[str, str]:
        """Map one validated clip's labels; all local voices remain distinct."""
        vectors = []
        labels = set()
        dimension = self._dimension
        for item in observations:
            label, raw = item["speaker_id"], item["embedding"]
            if label in labels:
                raise ValueError("duplicate_local_speaker")
            labels.add(label)
            if (
                not isinstance(raw, list)
                or not 1 <= len(raw) <= 1024
                or any(
                    type(x) not in (int, float)
                    or abs(x) > 1_000_000
                    or not math.isfinite(x)
                    for x in raw
                )
            ):
                raise ValueError("invalid_speaker_embedding")
            norm = math.hypot(*raw)
            if not norm:
                raise ValueError("invalid_speaker_embedding")
            if dimension is not None and len(raw) != dimension:
                raise ValueError("speaker_embedding_dimension_changed")
            dimension = len(raw)
            vectors.append((label, tuple(x / norm for x in raw)))
        # Decisions use the prior window's anchors, not local label order.
        # New voices in the same clip must never collapse into one identity.
        planned = []
        used = set()
        new_anchors = []
        for label, vector in vectors:
            scores = sorted(
                (
                    (math.fsum(a * b for a, b in zip(vector, anchor)), index)
                    for index, anchor in enumerate(self._anchors)
                ),
                reverse=True,
            )
            if not scores or scores[0][0] <= self.new_threshold:
                index = len(self._anchors) + len(new_anchors)
                new_anchors.append(vector)
            else:
                best, index = scores[0]
                if (
                    best < self.match_threshold
                    or (len(scores) > 1 and best - scores[1][0] < self.margin)
                    or index in used
                ):
                    raise ValueError("speaker_identity_ambiguous")
            used.add(index)
            planned.append((label, f"speaker_{index + 1:03d}"))
        if len(self._anchors) + len(new_anchors) > self.max_speakers:
            raise ValueError("recording_speaker_capacity")
        # A rejected clip cannot partially mutate recording identity state.
        self._anchors.extend(new_anchors)
        self._dimension = dimension
        return dict(planned)
