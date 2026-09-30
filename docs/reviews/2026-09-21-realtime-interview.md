# Local live interview: media-to-answer application integration

This batch connects the browser microphone to local WebRTC, CPU Silero VAD and
Smart Turn observations, provisional/final Qwen recognition, the existing durable
answer operation, local sentence audio, interruption and read-only recovery.
It is opt-in (`REALTIME_ENABLED=false` by default) and does not download weights.

## Actual execution and ownership

Authenticated HTTP negotiates one audio ingress track plus one ordered, reliable
control channel. Microphone audio is SRTP; control and bounded synthesized PCM
use DTLS/SCTP. There is no public STUN, TURN or cloud fallback. Explicit local
CIDRs and host/mDNS candidates restrict this initial local-network deployment.
NAT traversal beyond a local network is not implemented by this profile.

An expiring PostgreSQL lease under the interview record lock fences different
connections across application processes. Reconnecting the same client creates a
new connection epoch; a competing client is rejected until release/expiry. The
original JWT is revalidated every ten seconds and before finalization/commit.
Authentication and short state transactions close before inference/ICE waits.

The connection owns bounded ingress/control queues, detector state, at most one
provisional ASR call, one endpoint decision, one final draft and one playback.
Resumed speech invalidates a late endpoint observation. Provisional text is never
persisted or promoted into a final answer. Finalization re-decodes the complete
retained turn; overflow fails visibly instead of submitting a truncated answer.
The final draft remains in memory until explicitly confirmed. Automatic confirm
requires a separate user opt-in in the live control and is off by default.

Confirmation calls `mock_flow.submit_answer`, not a second interview state
machine. The browser saves only its request identity before dispatch. Existing
Phase A/Phase B receipts, immutable candidate answer, stale-question/version
fences and failure classification continue to apply. Reconnect reads HTTP state
and receipts. It never repeats a submitted request or regenerates a question.
The canonical answer is stored as text; this version does not retain the live
PCM as a downloadable original file. Its emitted draft hash is not an evidence
claim about persisted source audio. Uploaded-recording evidence remains separate.

Each sentence is synthesized by the existing local broker and sent in bounded
PCM blocks. The next sentence waits for completion of the previous browser
playback report, avoiding an unbounded playback queue. Speech onset or explicit
interrupt cancels synthesis and playback. Closing/unmounting stops tracks, aborts
HTTP, cancels tasks, closes the peer and AudioContext, and rejects late callbacks.

Generated, sent and client-reported sample counts are persisted separately and
readable from the owner-scoped playback history. Browser reports are not proof
of human perception, and a disconnected client's final unreported samples remain
unknown. No generated audio is called “heard”. The API does not infer a full
playback receipt when the client did not acknowledge it.

## Deliberate model/transport boundary

This is a working integration profile, not native model streaming: ASR currently
uses bounded incremental windows over the existing Qwen broker, and final text
uses full retained-turn windows. TTS is sentence-buffered Qwen CustomVoice, not
native streaming CosyVoice. The established interview operation still completes
its structured next-turn response before speech starts; this batch does not
claim DeepSeek token-to-audio streaming. Native stateful ASR, native streaming
TTS and token-level LLM/TTS scheduling remain explicit implementation work, not
hardware tests magically made complete by these interfaces.

Current model contracts are based on primary upstream implementations:
- https://aiortc.readthedocs.io/en/latest/api.html
- https://github.com/aiortc/aiortc/blob/main/examples/server/server.py
- https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py
- https://github.com/pipecat-ai/smart-turn/blob/main/inference.py

## Local configuration and acceptance

Install the optional `requirements/realtime.txt` alongside the API requirements
in the local API environment. Configure local ONNX paths and SHA256 hashes for
Silero and Smart Turn in `.env.local-first.example`. The detector loader verifies
bytes before creating CPU-only ONNX sessions. Select the already-prepared local Qwen ASR and TTS broker bindings explicitly.
The VAD and turn-end thresholds are provisional policy settings, not calibrated
accuracy estimates. No model assets, GPU or real microphone were tested here.

Dedicated CI `Realtime transport` installs aiortc and sets `REQUIRE_WEBRTC=1`.
Its native loopback test uses actual ICE, DTLS, SRTP, SCTP and audio resampling;
only model/detector/business callbacks are replaced. Absence of the transport
package fails this required job instead of producing a false pass. The portable
backend suite skips that single native test when the optional dependency is
absent. Browser-hook tests are deterministic lifecycle tests, not a claim of
physical microphone or acoustic echo quality.

Local validation: 457 backend tests passed, one optional native transport test
skipped because aiortc is absent. This includes the 16 portable realtime tests
and existing architecture, interview, voice, broker and local policy campaigns.
TypeScript, ESLint and production build passed. Generated live protocol schema
uses the existing locked openapi-typescript generator and its normal check gate.
