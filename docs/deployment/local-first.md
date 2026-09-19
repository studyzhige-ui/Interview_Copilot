# Local-first setup boundary (first implementation batch)

Status: evaluator and local-asset policy implemented; real-time audio, GPU
scheduling and pgvector switch are still pending. Do not interpret this guide as
a tested one-command installation of all future models. No production data is
migrated and no paid service is invoked by the preflight commands below.

## Reuse local assets

Merge the values needed from `.env.local-first.example` into your existing `.env`;
do not replace keys, database settings or paths. With `local_only`, the old online
edge-tts adapter is intentionally unavailable. Text mode and the existing local
recorded-audio review path remain the first validation targets. A local streaming
TTS adapter belongs to the next real-time work package, not an online fallback.

Keep the downloaded BGE embedding/reranker, Whisper, alignment, diarization and
Docling assets. `MODEL_ROOT_DIR` defaults to `CACHE_DIR/models`; it may instead
point at the existing read-only weight directory. In WSL a Windows `D:\...` path
must be translated to the corresponding `/mnt/d/...` path. Set `CACHE_DIR` to a
writable Linux directory for metadata/locks/Torch caches. Do not share Windows
and Linux virtual environments or compile caches.

```bash
# No network, model import, inference or writes to model/cache roots.
python scripts/doctor_local.py --model-root /mnt/d/Models/InterviewCopilot \
  --cache-dir /home/your-user/copilot-runtime/cache

# Optional full-file hash comparison when a managed download receipt exists.
python scripts/doctor_local.py --verify-hashes

# Optional read-only nvidia-smi query; NOT a Torch/CUDA kernel acceptance test.
python scripts/doctor_local.py --probe-gpu

# Local plan only; explicitly add --check-remote to request HF metadata.
python scripts/init_models.py --dry-run --only embedding
```

Replace example paths with your actual locations. The doctor exits 2 for missing
assets or policy conflicts, 0 when the selected structural checks pass. It always
reports that GPU/audio/model-quality acceptance was not performed. A custom
pipeline marked `bundle_requires_loader` still needs its actual offline loader.
Legacy unpinned weights are not assigned a made-up revision or trusted hash.

Actual `init_models.py --only <role>` is an explicit **online setup** action. It
resolves a commit, downloads into a separate revision, checks all expected files,
records hashes and atomically activates only a complete structural candidate.
Never use this command as an automatic model fallback inside an API request.
Back up valuable assets; no command here deletes the old model tree.

## Windows / WSL storage

Inspect before installing or moving anything:

```powershell
wsl --version
wsl --list --verbose
```

For a NEW distribution, Microsoft documents `wsl --install --distribution <name>
--location <folder>`. Choose a data-drive location with room for the distribution,
containers and temporary downloads. For an existing distribution, back up first;
this project does not run unregister, repartition or automatic destructive moves.
Keep Linux source/virtualenv/database/container data in the Linux filesystem,
with its virtual disk on the data drive. Reusing read-only Windows weight files
is deliberate; copy only a measured bottleneck, with space checks and hashes.

`.wslconfig` applies globally to WSL2. Memory/CPU/swap values are machine-specific
starting points, not performance claims. Put the swap file on the data drive when
the system drive is constrained. Do not install a separate Linux display driver
inside WSL; use the NVIDIA Windows driver path described by NVIDIA. The exact
Torch/vLLM/audio dependency set for a specific GPU is a later hardware gate.

Official references checked on 2026-09-19:
- [WSL install location and non-destructive inventory](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).
- [Windows/Linux filesystem placement](https://learn.microsoft.com/en-us/windows/wsl/filesystems).
- [WSL memory, processor and swap settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).
- [NVIDIA CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).
