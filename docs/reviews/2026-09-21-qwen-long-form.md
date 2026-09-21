# Qwen long-form upload evidence

## Implemented

`local_qwen_asr` now has an explicit complete-evidence collector. It runs under
the existing snapshot-owning worker and usage operation, and returns observations
to the same canonical compositor and database publication/version fences. The
WhisperX collector remains explicitly selectable; neither collector is fallback
for the other. The deployment default is not silently changed.

The existing FFmpeg PCM stream is reblocked into 26-second non-overlapping cores
with two seconds of context on each available side (at most 30 seconds per model
request). Only bounded decoder blocks/windows are held, not the full decoded
recording. The sample count determines duration; overlapping context does not
inflate it. The broker receives bounded PCM, never a source path or URL.

Each window uses broker-owned Qwen ASR, ForcedAligner and pyannote observations.
All three model/revision bindings are frozen once for the recording. The
application preserves the ASR's original punctuation/spacing in aligned source
slices. Unsupported normalization boundaries or missing lexical alignment fail
explicitly rather than inventing timestamps or changing text.

Boundary stitching uses a mutual, unique exact lexical match at overlapping
acoustic times, or an overlap region where neither side has words. Different
observations with no safe anchor are rejected. Repetition at different times is
not deduplicated. The continuing side supplies the anchor's text and separator,
preventing a seam from turning `Hello world` into `Helloworld`.

Speaker labels are local observations. Fixed normalized acoustic anchors map
them to recording-local identifiers; labels may swap between windows without
swapping those identifiers. Assignments are injective within a window. Ambiguous
matches, dimension changes and speaker-capacity overflow reject the operation.
Regular and exclusive tracks are intersected with the disjoint core intervals;
real simultaneous speech is preserved. Vectors remain transient and never enter
the durable transcript, receipts, or logs. No identity implies interviewer or
candidate role, which still requires the existing role-confirmation flow.

No partial graph is persisted. Complete parts exist only after decoder EOF.
Late decode/model/budget/identity errors after successful subcalls become an
unknown aggregate outcome, not a refundable "not started" operation or an
automatic retry. Decoder ownership/cleanup stays with the existing worker.

## Explicit configuration

After the separate model/environment acceptance step, the operator must match
the prepared broker to these application selections; wrong/missing bindings
fail rather than silently selecting another provider:

```dotenv
TRANSCRIPTION_PROVIDER=local_qwen_asr
TRANSCRIPTION_MODEL=Qwen/Qwen3-ASR-1.7B
TRANSCRIPTION_ALIGNMENT_MODEL=Qwen/Qwen3-ForcedAligner-0.6B
DIARIZATION_MODEL_ID=pyannote/speaker-diarization-community-1
```

Revisions must match `MODEL_REVISIONS_JSON` and the prepared broker configuration.
This batch does not download weights or change the installed model family.

## Validation and remaining acceptance

The initial local campaign ran 24 deterministic tests, including actual FFmpeg
60-second decoding and process cleanup on model-stage failure. It covers sample
boundaries, backpressure, input/output budgets, punctuation/spacing, repeated
words, label swaps, ambiguity, dimension changes, non-drifting speaker anchors,
language changes, overlap, cancellation and late failure. The model observations
are synthetic: this is not an ASR, alignment, diarization quality or GPU benchmark.
Full-dependency CI additionally exercises broker binding freeze, aggregate usage
classification, the capability entrypoint and existing canonical/database gates.

The default speaker thresholds (match 0.8, new 0.5, margin 0.1) are deliberately
explicit **uncalibrated policy parameters**, not probabilities. Rejecting an
ambiguous boundary or speaker is preferable to silently publishing corrupted
identity evidence, but real acceptance must measure rejection rate as well as
ASR/diarization accuracy. The 26/2-second window profile also needs real-corpus
boundary/latency evaluation. No claim is made that a 16 GB GPU fits all models
concurrently or meets real-time latency.

Still outside this batch: transcript correction/playback UX completion; P6
WebRTC/VAD/turn-end/streaming TTS/barge-in/reconnection; P7/P8 product convergence;
real DeepSeek quality calibration; model downloads and device/GPU acceptance.
