"""Voice / audio pipeline services — L4 (async interview audio analysis).

Submodules:
  - audio_transcription_service: provider-neutral long-form entry point
  - whisperx_engine: local WhisperX + Pyannote model runtime
  - tts_service:                 edge-tts wrapper

Submodules are imported lazily (no eager re-exports) so that optional
runtime dependencies — ``edge_tts``, ``whisperx``, etc. — only fail when
the feature is actually used.
"""
