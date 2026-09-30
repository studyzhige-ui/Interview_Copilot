"""Sample-exact context windows for complete, bounded recording evidence.

Each sample belongs to exactly one core. Context is observed more than once,
never counted twice in the recording duration. At most one decoder block and
one model window are buffered; no list of the recording's PCM is materialized.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

from app.local_inference.audio import MAX_PCM_BYTES, SAMPLE_RATE

CORE_SAMPLES = 26 * SAMPLE_RATE
CONTEXT_SAMPLES = 2 * SAMPLE_RATE


@dataclass(frozen=True)
class EvidenceWindow:
    pcm: bytes
    start: int
    core_start: int
    core_end: int

    @property
    def end(self) -> int:
        return self.start + len(self.pcm) // 2


async def evidence_windows(
    blocks: AsyncIterable[bytes], *, max_samples: int
) -> AsyncIterator[EvidenceWindow]:
    """Reblock bounded PCM into <=30s windows with disjoint <=26s cores."""
    if type(max_samples) is not int or max_samples <= 0:
        raise ValueError("invalid_evidence_sample_limit")
    iterator = aiter(blocks)
    buffer = bytearray()
    base = total = core_start = 0
    exhausted = False
    while True:
        target = core_start + CORE_SAMPLES + CONTEXT_SAMPLES
        while not exhausted and total < target:
            try:
                block = await anext(iterator)
            except StopAsyncIteration:
                exhausted = True
                break
            if (
                not isinstance(block, bytes)
                or not 0 < len(block) <= MAX_PCM_BYTES
                or len(block) % 2
            ):
                raise ValueError("invalid_evidence_pcm_block")
            total += len(block) // 2
            if total > max_samples:
                raise ValueError("audio_duration_exceeds_limit")
            buffer.extend(block)
        if core_start >= total:
            if not total:
                raise ValueError("audio_has_no_samples")
            return
        start = max(0, core_start - CONTEXT_SAMPLES)
        core_end = min(core_start + CORE_SAMPLES, total)
        end = min(target, total)
        pcm = bytes(buffer[2 * (start - base) : 2 * (end - base)])
        yield EvidenceWindow(pcm, start, core_start, core_end)
        core_start = core_end
        keep_from = max(0, core_start - CONTEXT_SAMPLES)
        del buffer[: 2 * (keep_from - base)]
        base = keep_from
