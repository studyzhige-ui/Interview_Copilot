# Preflight follows the implemented local speech configuration

`doctor_local.py` now recognizes Qwen ASR/alignment, local diarization and Qwen
preset-voice synthesis instead of reporting only the former WhisperX/Edge
selection. Synthesis includes its required local codec files; --verify-hashes
also requires codec files in the verified manifest. Explicit Edge selection is
still reported as a policy conflict under local_only.

When realtime is explicitly enabled, the report checks the configured absolute
VAD and endpoint detector files and their SHA256 declarations. Optional hash
verification reads bounded blocks, enforces the same 64 MiB asset limit as the
runtime, and never loads ONNX, starts inference, downloads assets, contacts a
broker or modifies files. Unconfigured, missing, invalid and hash-mismatched
assets have different diagnostic statuses.

A successful structural preflight is not readiness of the broker/interpreters,
GPU compatibility, recognition quality, latency or microphone acceptance.
`runtime`, `realtime` and `acceptance` fields preserve these distinctions;
package versions describe only the interpreter running the doctor. Native
model streaming remains separately identified as not implemented, rather than
being relabelled hardware acceptance.
