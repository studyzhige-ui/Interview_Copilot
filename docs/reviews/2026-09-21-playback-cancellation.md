# Playback cancellation: fence late responses, not only current audio

The existing mock recording button already called `tts.stop()`, but an HTTP
response arriving afterwards could still allocate a URL and start playback.
The shared useTts hook now owns a request, audio element and object URL per
playback generation. Stop, mute, voice change and unmount invalidate that
generation before aborting/disposing it. Responses, play promises and audio
events must still belong to the current generation before changing state.
A superseded request cannot start audio or clear a newer generation's URL.

The transport's AbortSignal is best effort; identity is the final fence. Empty
and oversized blobs fail explicitly. Autoplay rejection remains visible rather
than being labelled delivered/heard. These semantics follow the play() promise
contract documented at https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/play

Ten deterministic hook regressions passed, including deliberately ignored
HTTP cancellation and delayed play() settlement. TypeScript and ESLint passed.
Audio elements are test doubles: this is not a microphone, TTS-model, WebRTC,
streaming speech or actually-heard-audio acceptance result. No provider changed.
