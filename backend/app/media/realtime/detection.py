"""CPU Silero and Smart Turn observations, with a sample-counted speech gate.

Contracts: Silero 16k/512-sample ONNX (state + 64 context samples), Smart Turn
v3 ONNX input_features (Whisper, 8 seconds with left padding). Observations are
not calibrated truth. No silence timeout pretends to be semantic completion.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

FRAME_SAMPLES = 512
SAMPLE_RATE = 16000


def load_onnx(path: str, digest: str):
    # Operators select local model files; clients cannot submit paths or URLs.
    target = Path(path)
    if (
        not path
        or not target.is_absolute()
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
    ):
        raise ValueError("realtime_detector_not_configured")
    with target.open("rb") as source:
        data = source.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("realtime_detector_identity_mismatch")
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    return ort.InferenceSession(
        data, sess_options=options, providers=["CPUExecutionProvider"]
    )


def probability(value) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid_detector_probability")
    return value


class Detectors:
    """One serial CPU worker owns each connection's recurrent VAD state."""

    def __init__(self, config):
        import numpy as np
        from transformers import WhisperFeatureExtractor

        self.vad = load_onnx(config.vad_path, config.vad_sha256)
        self.endpoint = load_onnx(config.turn_path, config.turn_sha256)
        self.extractor = WhisperFeatureExtractor(chunk_length=8)
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def speech(self, pcm: bytes) -> float:
        import numpy as np

        if len(pcm) != FRAME_SAMPLES * 2:
            raise ValueError("invalid_detector_frame")
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32)[None, :] / 32768
        inputs = np.concatenate((self.context, audio), axis=1)
        result, state = self.vad.run(
            None,
            {
                "input": inputs,
                "state": self.state,
                "sr": np.array(SAMPLE_RATE, dtype=np.int64),
            },
        )
        if state.shape != (2, 1, 128) or not np.isfinite(state).all():
            raise ValueError("invalid_vad_state")
        self.state, self.context = state, inputs[:, -64:].copy()
        return probability(result.item())

    def ended(self, pcm: bytes) -> float:
        import numpy as np

        audio = (
            np.frombuffer(pcm[-8 * SAMPLE_RATE * 2 :], dtype="<i2").astype(np.float32)
            / 32768
        )
        audio = np.pad(audio, (8 * SAMPLE_RATE - len(audio), 0))
        features = self.extractor(
            audio,
            sampling_rate=SAMPLE_RATE,
            return_tensors="np",
            padding="max_length",
            max_length=8 * SAMPLE_RATE,
            truncation=True,
            do_normalize=True,
        ).input_features
        result = self.endpoint.run(
            None, {"input_features": features.astype(np.float32)}
        )
        return probability(result[0].reshape(-1)[0])


class SpeechGate:
    def __init__(self, threshold: float, silence_ms: int):
        self.threshold = threshold
        self.silence_samples = silence_ms * SAMPLE_RATE // 1000
        self.reset()

    def reset(self):
        self.active = False
        self.voiced = self.quiet = self.version = 0
        self.prefix = bytearray()

    def feed(self, pcm: bytes, score: float) -> tuple[bool, bytes]:
        if len(pcm) != FRAME_SAMPLES * 2:
            raise ValueError("invalid_live_frame")
        score = probability(score)
        self.prefix.extend(pcm)
        del self.prefix[: -FRAME_SAMPLES * 2 * 8]
        if score >= self.threshold:
            self.voiced += FRAME_SAMPLES
            self.quiet = 0
            self.version += 1
        elif score < max(0, self.threshold - 0.15):
            self.voiced = 0
            self.quiet += FRAME_SAMPLES
        started = not self.active and self.voiced >= FRAME_SAMPLES * 6
        if started:
            self.active = True
            return True, bytes(self.prefix)
        return False, pcm if self.active else b""

    @property
    def may_end(self):
        return self.active and self.quiet >= self.silence_samples
