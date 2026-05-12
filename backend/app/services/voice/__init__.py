"""Voice / audio pipeline services — L4 (async interview audio analysis).

Submodules:
  - audio_transcription_service: WhisperX + Pyannote diarization
  - interview_analysis_service:  Three-stage MapReduce analysis pipeline
  - file_parser:                 Resume/media file parsing utilities
  - tts_service:                 edge-tts wrapper

Submodules are imported lazily (no eager re-exports) so that optional
runtime dependencies — ``edge_tts``, ``whisperx``, etc. — only fail when
the feature is actually used.
"""
