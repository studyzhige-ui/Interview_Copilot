"""Finite PCM diarization observations, not user roles or verified identities.

The configured child returns regular/exclusive tracks and filtered acoustic
observations. A label is local to this request; recording-level identity belongs to
the evidence application. Raw vectors must never enter logs or usage receipts.
"""

from __future__ import annotations

import math
import re
import base64
import binascii
import struct

from .audio import SAMPLE_RATE, decode_pcm
from .errors import ProtocolError

DIARIZATION_CONTRACT = "pyannote-community-pcm16-recording-observations-v4"
DIARIZATION_MAX_SPEAKERS = 32
DIARIZATION_MAX_INTERVALS = 4096
DIARIZATION_MAX_DIMENSION = 1024
DIARIZATION_BINDING_TOKENS = 4096
MAX_RECORDING_OBSERVATIONS = 8192
MAX_WINDOW_OBSERVATIONS = 256


def _validate_embeddings(vectors, limit):
    if not isinstance(vectors, list) or len(vectors) > limit:
        raise ProtocolError("diarization_observation_capacity")
    dimension = None
    for vector in vectors:
        if (
            not isinstance(vector, list)
            or not 1 <= len(vector) <= DIARIZATION_MAX_DIMENSION
            or (dimension is not None and len(vector) != dimension)
            or any(not _number(x) or abs(x) > 1_000_000 for x in vector)
            or not any(x != 0 for x in vector)
        ):
            raise ProtocolError("invalid_speaker_embedding")
        dimension = len(vector)
    return dimension


def encode_embeddings(vectors):
    dimension = _validate_embeddings(vectors, MAX_RECORDING_OBSERVATIONS)
    if not dimension:
        raise ProtocolError("empty_recording_observations")
    # Preserve the model's float32 values without expanding an hour's acoustic
    # observations into millions of JSON decimal strings.
    raw = b"".join(struct.pack(f"<{dimension}f", *vector) for vector in vectors)
    return {"dimension": dimension, "data": base64.b64encode(raw).decode("ascii")}


def decode_embeddings(value):
    if not isinstance(value, dict) or set(value) != {"dimension", "data"}:
        raise ProtocolError("invalid_recording_observations")
    dimension, data = value["dimension"], value["data"]
    if (
        type(dimension) is not int
        or not 1 <= dimension <= DIARIZATION_MAX_DIMENSION
        or not isinstance(data, str)
        or not 0
        < len(data)
        <= (MAX_RECORDING_OBSERVATIONS * dimension * 4 + 2) // 3 * 4
    ):
        raise ProtocolError("invalid_recording_observations")
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProtocolError("invalid_recording_observations") from exc
    if (
        len(raw) % (dimension * 4)
        or not 0 < len(raw) <= MAX_RECORDING_OBSERVATIONS * dimension * 4
    ):
        raise ProtocolError("invalid_recording_observations")
    vectors = [list(row) for row in struct.iter_unpack(f"<{dimension}f", raw)]
    _validate_embeddings(vectors, MAX_RECORDING_OBSERVATIONS)
    return vectors


def validate_clustering_request(task):
    if (
        type(task["min_speakers"]) is not int
        or type(task["max_speakers"]) is not int
        or not 1
        <= task["min_speakers"]
        <= task["max_speakers"]
        <= DIARIZATION_MAX_SPEAKERS
    ):
        raise ProtocolError("invalid_recording_clustering")
    decode_embeddings(task["embeddings"])
    return task


def validate_clustering_result(task, value):
    if not isinstance(value, list) or not 1 <= len(value) <= task["max_speakers"]:
        raise ProtocolError("invalid_recording_clusters")
    _validate_embeddings(value, task["max_speakers"])
    expected_dimension = task["embeddings"]["dimension"]
    if len(value[0]) != expected_dimension:
        raise ProtocolError("invalid_recording_cluster_dimension")
    return value


def validate_diarization_request(task):
    decode_pcm(task["audio"])
    if (
        task["operation"] != "diarize"
        or type(task["max_speakers"]) is not int
        or not 1 <= task["max_speakers"] <= DIARIZATION_MAX_SPEAKERS
    ):
        raise ProtocolError("invalid_diarization_operation")
    _validate_embeddings(task["centroids"], task["max_speakers"])
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
        "embeddings",
    }:
        raise ProtocolError("invalid_diarization_result")
    _validate_embeddings(value["embeddings"], MAX_WINDOW_OBSERVATIONS)
    if task["centroids"] and value["embeddings"]:
        raise ProtocolError("reconstruction_must_not_return_observations")
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
                or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity) is None
            ):
                raise ProtocolError("invalid_diarization_interval")
            previous_start, previous_end = start, end
            seen.add(identity)
        labels[name] = seen
    identities = labels["regular"]
    if (
        len(identities) > task["max_speakers"]
        or not labels["exclusive"] <= identities
        or (identities and not labels["exclusive"])
    ):
        raise ProtocolError("diarization_track_identity_mismatch")
    return value
