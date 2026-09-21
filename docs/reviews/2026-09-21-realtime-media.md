# Local-network realtime interview media

This is an integrated repository implementation, not a model-quality or device
acceptance claim. It adds an optional WebRTC microphone and reliable control/PCM
channel to the existing mock interview, not a parallel interview business engine.

## Enablement

Install the pinned `realtime` optional dependencies (`pip install -e '.[dev,realtime]'`)
in the API interpreter. Apply migration 0059 through the normal Alembic workflow.
Explicitly set REALTIME_ENABLED=true, configure local_qwen_asr and local_qwen3_tts,
and start their existing broker. No weights are downloaded by the API or scripts.
The voice page has a separate realtime connect control; existing text and recorded
answer modes remain available and cannot submit concurrently with a live session.

The default candidate policy permits numeric loopback addresses only. Set
REALTIME_ALLOWED_CIDRS to the exact trusted client/WSL/LAN ranges when needed. UDP
must be routable between browser and API. There is no public STUN, TURN, relay or
implicit cloud fallback. Browsers publishing only mDNS ICE candidates are rejected;
this profile is therefore not a universal Internet deployment. Use HTTPS except
for browser-trusted localhost. Deployment of NAT traversal and production network
policy is not included in this profile. Model/API processes remain separate.

## User scenario and ownership

Connect explicitly, speak, inspect rolling previews, and confirm the final draft.
The default silence rule only forms a draft; it never authorizes submission.
An explicit hands-free checkbox allows acoustic endpoint detection to submit a
final result. It is not semantic sentence-completion detection. Users can end an
utterance, discard a draft, or disconnect and edit the displayed text. Microphone
and page teardown, stale permissions and old connection callbacks are fenced.

A stable client_session_id is retained per browser session. The database holds a
generation-fenced lease per record/client; reconnect revokes earlier generations.
Authenticated HTTP heartbeat renews the lease; possession of an existing DTLS
channel cannot renew revoked HTTP authentication. Disconnected media tasks release
resources. Once the canonical answer transaction starts it retains ownership and
finishes its existing answer receipt; reconnect only reads that receipt and live
state. It does not regenerate a question or replay provisional transcription.

RTP microphone frames are resampled to 16 kHz mono PCM16. The debounced RMS VAD
uses sample-count duration limits, 24-second segments, bounded preroll and silence
hangover. A bounded queue serializes final ASR. Rolling previews reuse the finite
Qwen broker operation and are metered for the work actually dispatched. They are
not a native stateful streaming decoder. Raw microphone PCM and provisional text
are not persisted by this transport. This does not provide an archived source
recording for subsequent word-level audio evidence. Final text uses the existing
submit_answer application transaction, ownership, question fence and usage scope.

The interviewer text is synthesized in punctuation-aware bounded chunks. The next
chunk can be generated while the previous chunk plays. This is incremental delivery
of finite local synthesis, not token-level native streaming TTS. Confirmed candidate
speech interrupts queued/generating playback; the saved question remains intact.
Buffer, byte, sample, control queue, peer count, lifetime and handshake bounds fail
visibly, rather than silently dropping finalized words or retrying model work.

## Playback semantics

Each generated PCM chunk has an audio id, text/PCM hashes, sample count and model
pipeline provenance through the existing usage ledger. Browser reports are checked
for generation, ownership and monotonic sample bounds. They are stored as
`client_reported`, never `heard`. Web Audio scheduling is not proof that the user
heard the sound; muted outputs, suspended devices and dishonest clients are not
observable acoustic facts. Partial/interrupted playback is not completed playback.

## Validation and remaining acceptance

The deterministic campaign covers draft/commit isolation, stale ASR and question
fences, explicit auto-submit, cancellation, accepted-answer ownership, barge-in,
lease replacement, receipts, HTTP authentication and resource bounds. A real
aiortc loopback uses DTLS/SRTP, Opus RTP, a reliable datachannel, actual PyAV
resampling and generated PCM delivery; only speech/model application results are
substituted. The required browser CI job installs realtime dependencies and runs
this test with REQUIRE_REALTIME=1, so a missing SDK cannot hide behind a skip.

Still required locally: actual mic/browser/WSL interoperability, audible playout,
echo cancellation, VAD false-end rates, ASR quality, model startup/VRAM and latency.
Native streaming model adapters, semantic endpoint detection, Internet TURN and
universal browser ICE support are not claimed complete by this implementation.

References: aiortc API documentation https://aiortc.readthedocs.io/en/latest/api.html
and browser Web Audio/WebRTC specifications documented by MDN. Optional SDK/AV
versions are pinned in pyproject.toml and do not change the base ML environment.
