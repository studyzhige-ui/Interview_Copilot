"""Sample-exact context windows for complete, bounded recording evidence.

Each sample belongs to exactly one core. Context is observed more than once,
never counted twice in the recording duration. A bounded rolling context and
decoder lookahead are retained; no recording-sized PCM list is materialized.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Callable
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
    blocks: AsyncIterable[bytes],
    *,
    max_samples: int,
    choose_end: Callable[[bytes, int, int], int],
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
        # A non-final core ends at a speech boundary selected from this bounded
        # observation. Samples beyond that boundary remain for the next core.
        if core_end < total:
            chosen = choose_end(pcm, core_start - start, core_end - start)
            if (
                type(chosen) is not int
                or not core_start - start < chosen <= core_end - start
            ):
                raise ValueError("invalid_evidence_core_boundary")
            core_end = start + chosen
            end = min(core_end + CONTEXT_SAMPLES, total)
        # Fill unused model capacity with prior context, especially for a short
        # final core. Otherwise its speaker embedding can lose continuity merely
        # because only a few seconds remain. ASR still sees only the disjoint core.
        start = max(0, end - MAX_PCM_BYTES // 2)
        pcm = bytes(buffer[2 * (start - base) : 2 * (end - base)])
        yield EvidenceWindow(pcm, start, core_start, core_end)
        core_start = core_end
        keep_from = max(0, core_start - MAX_PCM_BYTES // 2)
        del buffer[: 2 * (keep_from - base)]
        base = keep_from
