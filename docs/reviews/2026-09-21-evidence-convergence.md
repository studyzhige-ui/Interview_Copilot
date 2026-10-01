# Evidence convergence — provider-neutral composition and source fencing

## Implemented in this batch

The upload application selects a complete evidence capability, not a WhisperX
condition. Providers return aligned ASR words and regular/exclusive global
speaker observations; one compositor assigns canonical word identities and
validates completion, time bounds, ordering, output capacities and model identity.
ASR-only and remote providers are rejected before file or usage admission.

The operation captures an authorized file into a bounded, read-only on-disk
snapshot before inference. Its SHA-256 is checked against a declared hash version.
Original-file mutation/replacement and snapshot mutation prevent publication.
The synchronous worker owns snapshot cleanup even when its async waiter cancels.
This is resource/lifecycle isolation, not an operating-system security sandbox.

The analysis orchestrator freezes one resolved provider and records that actual
provider. Transcript publication locks and refreshes both the review record and
source asset, then checks owner, reference, version, checksum and deletion/upload
state before appending evidence. The existing review-generation fence remains.

WhisperX is an explicit migration/benchmark adapter. It reports loaded model
identities, not relabelled current settings, and no longer composes the canonical
evidence graph itself. The previous ASR-only rejection test has moved into the
provider-capability suite, with additional no-admission/no-fallback checks.

## Verification boundaries

Deterministic tests cover the compositor, real temporary files, fixed-block
copying, cancellation lifetime and the WhisperX adapter with fake model outputs.
A PostgreSQL regression covers a stale ORM identity map after another session
commits a source-version change. Real PostgreSQL/browser/worker CI gates remain;
local pure-Python or fake-model results are not substitutes for those gates.

## Still not implemented

Qwen finite-clip ASR is not yet a complete upload-evidence capability. The full
Qwen/alignment/global-diarization/long-form stitching collector remains required.
The WhisperX comparison adapter still decodes the entire recording in memory;
only source capture is bounded here. No streaming-ASR, microphone, WebRTC, real
model quality, latency or RTX 5060 Ti GPU acceptance is claimed by this batch.

No model weights or paid provider calls are required by this repository batch.
