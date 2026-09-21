# Microphone capture lifetime and bounded recording

The shared recorder now owns each getUserMedia request and MediaRecorder through
an identity checked by every asynchronous callback. Cancelling while permission
is pending, starting a new capture, and unmounting cannot leave a late grant
recording: its tracks are immediately stopped. Rapid starts share one pending
request, and repeated stops share the same final-result promise rather than
replacing another caller's onstop handler.

Permission waiting is limited to 60 seconds. Recording is limited to ten minutes
and 25 MiB, with periodic data delivery; exceeding either limit discards the
partial recording with a visible error, never silently submits a truncated
answer. Missing final recorder events fail within five seconds. Device errors
and teardown stop tracks, clear timers, detach callbacks, and resolve waiters.
These are application bounds, not a promise that browser scheduling always
fires timers on time while a tab/device is suspended.

The browser permission prompt itself cannot be cancelled by this hook. The
getUserMedia promise may remain pending when the user does not decide, and
MediaRecorder.stop delivers its final data before the stop event. References:
https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/stop

Ten deterministic hook regressions cover late permission, concurrent starts,
repeated stops, missing events, resource limits and teardown. The combined
recorder/TTS/mock-page/upload campaign passes 38 tests; TypeScript and ESLint pass.
These use test devices. No real microphone, browser end-to-end recording,
WebRTC, streaming ASR/TTS or hardware acceptance is implied.

The upload request now shares this page lifetime through AbortSignal plus an
identity fence. A late transcription cannot overwrite a new page; each record
mount owns fresh UI state. MP4, Ogg, WebM and WAV blobs preserve the actual
container in their upload filename. Limits are shown before recording. Network
cancellation is best effort, not proof that already-dispatched model work was
refunded or never executed.
