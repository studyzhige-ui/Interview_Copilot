# Broker-owned finite diarization

## Implemented

The existing local inference broker now accepts a distinct, version-bound
`diarization` PCM role. It uses the same private socket, admission queue,
owned-process cancellation, explicit CUDA selection and unknown-outcome rules
as the existing ASR/alignment roles. Requests cannot supply file paths, URLs,
provider credentials or executable code. No cloud fallback is added.

The isolated pyannote.audio 4 adapter loads an explicitly prepared local
Community pipeline, processes at most 30 seconds per call, and returns regular
and exclusive intervals plus speaker vectors in the official label order.
Silence is represented by empty observations. Nonfinite/zero/inconsistent
vectors, unknown labels, excessive output and invalid/overlapping exclusive
times fail closed. Regular-track overlap is retained. Labels remain local to
one call: this batch does not claim recording-level speaker identity.

The preparation script accepts separate `--diarization-python` and
`--diarization-model` options. It checks the complete local pipeline-bundle
candidate without installing packages or downloading weights. Component loading
remains an explicit model acceptance check. Runtime telemetry is disabled before
pyannote import; keys and Hugging Face download tokens are not inherited.

## Verification

124 deterministic tests passed locally: diarization contract/adapter/client,
ASR/alignment, broker, IPC, real FFmpeg PCM decoder and the full import-graph
checks. Ruff and compileall passed. Adapter tests use fake model outputs; these
are not pyannote quality, GPU, latency, or hardware acceptance results.

A broader directory collection encountered a missing local `llama_index`
dependency. Its existing adapter tests were neither removed nor marked passed;
the normal full-dependency CI continues to execute them.

## Integration boundary

The complete Qwen recording collector is a separate application batch: bounded
windows, lossless text-to-word projection, versioned recording speaker matching,
completion and publication fences. This broker batch alone does not register a
full upload collector or change the default transcription provider.

## Upstream contracts checked on 2026-09-21

- `https://huggingface.co/pyannote/speaker-diarization-community-1`
- `https://github.com/pyannote/pyannote-audio/blob/develop/src/pyannote/audio/pipelines/speaker_diarization.py`
- `https://github.com/pyannote/pyannote-audio/blob/main/src/pyannote/audio/telemetry/metrics.py`
