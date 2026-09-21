"""Finite PCM diarization observations, not user roles or verified identities.

The configured child returns regular/exclusive local labels and their acoustic
vectors. A label is local to this request; recording-level identity belongs to
the evidence application. Raw vectors must never enter logs or usage receipts.
"""

from __future__ import annotations

import math
import re

from .audio import SAMPLE_RATE, decode_pcm
from .errors import ProtocolError

DIARIZATION_CONTRACT = "pyannote-community-pcm16-speaker-vectors-v1"
DIARIZATION_MAX_SPEAKERS = 32
DIARIZATION_MAX_INTERVALS = 4096
DIARIZATION_MAX_DIMENSION = 1024
DIARIZATION_BINDING_TOKENS = 4096


def validate_diarization_request(task):
    decode_pcm(task["audio"])
    if (
        task["operation"] != "diarize"
        or task["text"] != ""
        or task["language"] is not None
    ):
        raise ProtocolError("invalid_diarization_operation")
    return task


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_diarization_result(task, value):
    if not isinstance(value, dict) or set(value) != {
        "regular",
        "exclusive",
        "speakers",
    }:
        raise ProtocolError("invalid_diarization_result")
    speakers = value["speakers"]
    if not isinstance(speakers, list) or len(speakers) > DIARIZATION_MAX_SPEAKERS:
        raise ProtocolError("diarization_speaker_capacity")
    identities = set()
    dimension = None
    for speaker in speakers:
        if not isinstance(speaker, dict) or set(speaker) != {"speaker_id", "embedding"}:
            raise ProtocolError("invalid_speaker_observation")
        identity, vector = speaker["speaker_id"], speaker["embedding"]
        if (
            not isinstance(identity, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity) is None
            or identity in identities
        ):
            raise ProtocolError("invalid_speaker_identity")
        if (
            not isinstance(vector, list)
            or not 1 <= len(vector) <= DIARIZATION_MAX_DIMENSION
            or (dimension is not None and len(vector) != dimension)
            or any(not _number(x) or abs(x) > 1_000_000 for x in vector)
            or not any(x != 0 for x in vector)
        ):
            raise ProtocolError("invalid_speaker_embedding")
        dimension = len(vector)
        identities.add(identity)
    duration = task["audio"]["samples"] / SAMPLE_RATE
    labels = {}
    for name in ("regular", "exclusive"):
        rows = value[name]
        if not isinstance(rows, list) or len(rows) > DIARIZATION_MAX_INTERVALS:
            raise ProtocolError("diarization_interval_capacity")
        previous_start = previous_end = 0.0
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"start", "end", "speaker_id"}:
                raise ProtocolError("invalid_diarization_interval")
            start, end, identity = row["start"], row["end"], row["speaker_id"]
            if (
                not _number(start)
                or not _number(end)
                or not 0 <= start < end <= duration
                or start < previous_start
                or (name == "exclusive" and start < previous_end)
                or not isinstance(identity, str)
                or identity not in identities
            ):
                raise ProtocolError("invalid_diarization_interval")
            previous_start, previous_end = start, end
            seen.add(identity)
        labels[name] = seen
    # Silence has three empty lists. Missing embeddings or only one kind of
    # track is not silently accepted as a complete diarization observation.
    if (
        labels["regular"] != identities
        or not labels["exclusive"] <= identities
        or (identities and not labels["exclusive"])
    ):
        raise ProtocolError("diarization_track_identity_mismatch")
    return value
