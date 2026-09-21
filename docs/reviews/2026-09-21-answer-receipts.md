# Durable committed-answer intents

A transport reconnect must not be a new DeepSeek generation. The existing
mock-flow application operation now requires a canonical UUID request_id and
stores its digest, question, claim generation and terminal response in migration
0058. It still owns the same two short transactions and one model await. There
is no second interview engine or media business state machine.

Record ownership is checked before any HTTP receipt read. New submissions lock
the interview record, refresh the runtime and claim its question. The intent,
saved candidate message and lease commit together before the model await. A
successful assistant message, runtime advance and completed response receipt
commit together. Same-ID/different-text/question/clip requests conflict. Same-ID
completed requests return the original response even after runtime teardown;
in-progress/unknown requests never redispatch. Read-only expiry reports unknown
and does not release a lease or authorize retry. A new, explicitly requested
intent may retry the existing immutable answer after release/lease expiration.
Late results still fail the original generation fence. Cancellation/failure
marks only that attempt unknown and releases only its lease, in the shared
record -> runtime -> receipt lock order. Lost-response cleanup never downgrades
a completed receipt. Per-record intent capacity is bounded at 1000.

The frontend persists only request/question identity in sessionStorage. It does
not persist answer text, audio or tokens. Reload and network recovery use GET;
while a receipt is in progress, the regenerate button is not offered. The
explicit regenerate action creates a new UUID, retaining the extra-call warning.
Old clients must update with the backend: a missing request_id is now a 422,
not a silently generated server-side key that defeats response-loss recovery.

Validation includes model-await transaction absence, exact replay, mismatch,
unknown/cancellation, HTTP ownership and malformed input. A dedicated real
PostgreSQL test exercises two sessions contending for one intent, read-only
in-progress status, replay, runtime removal and record-delete cascading. It must
run in the normal PostgreSQL CI; local SQLite results are not substitutes.

This is the durable answer/reconnect boundary needed by P6, not a claim that
WebRTC, VAD/turn-end, streaming ASR/TTS or hardware acceptance is complete.
No models are downloaded or called by these deterministic regressions.
