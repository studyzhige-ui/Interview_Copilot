"""Sample-clock energy endpointing with pre-roll and bounded continuous speech.

This is a deterministic acoustic detector, NOT semantic turn-end prediction.
Silence proposes a final draft. Automatic submission is explicit session opt-in.
"""

from array import array
from collections import deque
from dataclasses import dataclass
import math
import sys

RATE = 16000
FRAME_SAMPLES = 320
FRAME_BYTES = FRAME_SAMPLES * 2


@dataclass(frozen=True)
class VoiceEvent:
    kind: str
    pcm: bytes = b""


class VoiceActivity:
    def __init__(self, *, threshold: float = 0.015, silence_ms: int = 900):
        if (
            type(threshold) not in (int, float)
            or not math.isfinite(threshold)
            or not 0 < threshold < 1
        ):
            raise ValueError("invalid_vad_threshold")
        if type(silence_ms) is not int or not 300 <= silence_ms <= 3000:
            raise ValueError("invalid_vad_silence")
        self.threshold = threshold
        self.silence_frames = (silence_ms + 19) // 20
        self.reset()

    def reset(self):
        self.active = False
        self.onset = self.silent = self.speech_frames = self.total_frames = 0
        self.pre = deque(maxlen=10)
        self.buffer = bytearray()

    def feed(self, frame: bytes) -> list[VoiceEvent]:
        if not isinstance(frame, bytes) or len(frame) != FRAME_BYTES:
            raise ValueError("invalid_live_pcm_frame")
        samples = array("h", frame)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(x * x for x in samples) / FRAME_SAMPLES) / 32768
        voiced = rms >= self.threshold
        events = []
        if not self.active:
            self.pre.append(frame)
            self.onset = self.onset + 1 if voiced else 0
            if self.onset < 4:  # 80 ms debounce; preserve earlier samples in pre-roll.
                return events
            self.active = True
            self.buffer.extend(b"".join(self.pre))
            self.pre.clear()
            self.speech_frames = self.onset
            self.total_frames = len(self.buffer) // FRAME_BYTES
            events.append(VoiceEvent("start"))
        else:
            self.buffer.extend(frame)
            self.total_frames += 1
            self.speech_frames += int(voiced)
        self.silent = 0 if voiced else self.silent + 1
        if self.total_frames > 30_000:  # Ten minutes, not unlimited background capture.
            self.reset()
            raise ValueError("utterance_duration_limit")
        if self.silent >= self.silence_frames:
            events.append(self.finish())
        elif len(self.buffer) >= RATE * 24 * 2:
            events.append(VoiceEvent("segment", bytes(self.buffer)))
            self.buffer.clear()
        return events

    def finish(self) -> VoiceEvent:
        if not self.active:
            return VoiceEvent("empty")
        # Very brief clicks/noise are never a final candidate answer.
        result = (
            VoiceEvent("final", bytes(self.buffer))
            if self.speech_frames >= 10
            else VoiceEvent("empty")
        )
        self.reset()
        return result

    def preview(self) -> bytes:
        return bytes(self.buffer) if self.active else b""
