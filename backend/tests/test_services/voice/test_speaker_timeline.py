"""Temporal overlap evidence cannot be inferred from multiple touched turns."""

from random import Random

import pytest

from app.media.application.speaker_timeline import SpeakerTimeline
from app.media.application.transcript_evidence import DiarizationInterval
from tests.test_services.voice.test_transcript_evidence import _evidence


def interval(start, end, speaker):
    return DiarizationInterval(start=start, end=end, speaker_id=speaker)


@pytest.mark.parametrize("gap", [0.0, 0.2])
def test_crossing_adjacent_or_separated_speakers_is_not_overlap(gap):
    tracks = [interval(0, 1, "A"), interval(1 + gap, 2, "B")]
    speaker, confidence, overlap = SpeakerTimeline(tracks, tracks).assign(0.5, 1.5)
    assert speaker == "A" and confidence == 0.5
    assert overlap is False


def test_same_speaker_duplicates_do_not_invent_a_second_voice():
    regular = [interval(0, 4, "A"), interval(1, 2, "A"), interval(1, 2, "A")]
    timeline = SpeakerTimeline(regular, [interval(0, 4, "A")])
    assert timeline.assign(1.5, 2.5) == ("A", 1.0, False)


def test_nested_same_speaker_does_not_end_outer_active_interval():
    regular = [interval(0, 4, "A"), interval(1, 2, "A"), interval(2.5, 3, "B")]
    timeline = SpeakerTimeline(regular, [interval(0, 4, "A")])
    assert timeline.assign(2, 2.5) == ("A", 1.0, False)
    assert timeline.assign(2.5, 3) == ("A", 1.0, True)
    assert timeline.assign(3, 3.5) == ("A", 1.0, False)


def test_overlap_is_independent_of_exclusive_identity_and_missing_coverage():
    regular = [interval(0, 2, "A"), interval(1, 3, "B")]
    timeline = SpeakerTimeline(regular, [interval(0, 0.5, "A")])
    assert timeline.assign(1, 2) == (None, None, True)
    assert timeline.assign(2, 3) == (None, None, False)


def test_canonical_graph_uses_index_without_rewriting_raw_tracks():
    evidence = _evidence()
    assert evidence.words[-1].speaker_id == "SPEAKER_00"
    assert evidence.words[-1].overlap is True
    assert len(evidence.diarization.regular) == 2
    assert evidence.diarization.regular[0].end == 1.6
    assert evidence.diarization.exclusive[0].end == 1.45


def test_index_agrees_with_independent_interval_intersection_reference():
    rng = Random(1729)
    regular = []
    for _ in range(60):
        start = rng.randrange(0, 100) / 10
        regular.append(
            interval(start, start + rng.randrange(1, 30) / 10, str(rng.randrange(3)))
        )
    exclusive = [interval(i / 2, (i + 1) / 2, str(i % 3)) for i in range(30)]
    timeline = SpeakerTimeline(regular, exclusive)
    # Intentionally unordered queries and variable-length words: no cursor may
    # drop evidence when an earlier word extends beyond a later word's end.
    for _ in range(200):
        start = rng.randrange(0, 150) / 10
        end = start + rng.randrange(1, 40) / 10
        scores = {}
        for row in exclusive:
            amount = max(0, min(end, row.end) - max(start, row.start))
            if amount:
                scores[row.speaker_id] = scores.get(row.speaker_id, 0) + amount
        expected_speaker = max(scores, key=scores.get) if scores else None
        expected_confidence = (
            scores[expected_speaker] / (end - start) if scores else None
        )
        expected_overlap = any(
            left.speaker_id != right.speaker_id
            and max(start, left.start, right.start) < min(end, left.end, right.end)
            for left in regular
            for right in regular
        )
        speaker, confidence, overlap = timeline.assign(start, end)
        assert speaker == expected_speaker, (start, end)
        assert confidence == pytest.approx(expected_confidence), (start, end)
        assert overlap is expected_overlap, (start, end)
