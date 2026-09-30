"""Bounded synthesis segmentation and untrusted client playback observations."""

from __future__ import annotations
import io
import re
import wave
from dataclasses import dataclass


def sentences(text: str):
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        raise ValueError("invalid_spoken_text")
    # Every source character stays present; this is not an LLM summarization.
    for sentence in re.split(r"(?<=[。！？.!?\n])", text):
        for start in range(0, len(sentence), 240):
            if (part := sentence[start : start + 240]).strip():
                yield part


def pcm_from_wav(data: bytes) -> bytes:
    if not isinstance(data, bytes) or len(data) > 2_880_044:
        raise ValueError("invalid_live_synthesis")
    with wave.open(io.BytesIO(data), "rb") as audio:
        if (
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getframerate(),
            audio.getcomptype(),
        ) != (1, 2, 24000, "NONE"):
            raise ValueError("invalid_live_synthesis")
        pcm = audio.readframes(1_440_001)
        if not pcm or len(pcm) != audio.getnframes() * 2 or len(pcm) > 2_880_000:
            raise ValueError("invalid_live_synthesis")
        return pcm


@dataclass
class Playback:
    id: str
    message_id: int
    generated: int = 0
    delivered: int = 0
    reported: int = 0

    def acknowledge(self, samples: int):
        if type(samples) is not int or not self.reported <= samples <= self.delivered:
            raise ValueError("invalid_playback_ack")
        self.reported = samples

    def snapshot(self, status: str):
        return {
            "playback_id": self.id,
            "message_id": self.message_id,
            "generated_samples": self.generated,
            "delivered_samples": self.delivered,
            "client_reported_samples": self.reported,
            "sample_rate": 24000,
            "status": status,
        }
