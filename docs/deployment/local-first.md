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


## Explicit local loader/inference probe (P1 continuation)

`doctor_local.py` remains read-only and does not import models. After that
structural check, the new command below can explicitly load **one existing
model** in a separate Linux/WSL2 interpreter and run a small synthetic input:

```bash
python scripts/probe_local_model.py --role embedding \
  --python /home/your-user/local-ml/.venv/bin/python \
  --model-root /mnt/d/Models/InterviewCopilot \
  --cache-dir /home/your-user/copilot-runtime/cache --device cuda
```

The ML environment must already contain the selected role's dependencies. The
command does not install or download them, change the production model, use the
DeepSeek key, or change existing model roots. The existing configured model ID
is used unless `--model` is explicit. `--timeout` defaults to 180 seconds per
probe; the child is stopped/reaped before the temporary cache is removed.

Supported probes: `embedding` via SentenceTransformer, `reranking` via
CrossEncoder, `transcription` via faster-whisper/CT2, and `alignment` via the
local Transformers CTC model. They consume the synthetic inference result;
creating a lazy transcription generator is not counted as a successful test.
This does not certify WhisperX's complete alignment/diarization pipeline,
Docling bundles, model quality, microphone, real-time voice or single-card
co-residency. Those acceptance items remain open. CUDA is explicit and does not
silently fall back to CPU. CPU is the default for an unqualified invocation.

Each process receives only an allowlisted environment, private temporary HOME
and offline cache roots, and no provider credentials, proxy settings, Python
path or database URL. SDK offline options plus Python socket audit checks stop
ordinary downloads/network calls. **They are not an OS security sandbox against
malicious local model code or native libraries.** Use trusted assets, read-only
weight mounts and an OS/network-isolated host for stronger containment.

The combined stdout/stderr budget is bounded. Logs are not included in the JSON
report; request ID, role, protocol and exit status must agree. Deadline, output
flood, repeated cancellation and descendants holding a pipe are tested using
real subprocesses. POSIX process groups are used; Windows-native execution is
rejected instead of pretending that `Process.kill()` kills an entire tree.
The GPU is initialized only in the fresh interpreter, not before a Celery fork.

A success means one synthetic loader smoke completed in the selected environment.
It is not P2's shared GPU scheduler and does not make P3–P9 complete. Missing
weights/dependencies or failed inference exit nonzero, never `skipped=passed`.

Official references checked 2026-09-20:
- [Python subprocess lifecycle and pipes](https://docs.python.org/3.13/library/asyncio-subprocess.html).
- [PyTorch accelerator/fork limitations](https://docs.pytorch.org/docs/stable/notes/multiprocessing.html).
- [SentenceTransformer local loading](https://sbert.net/docs/package_reference/sentence_transformer/model.html).
- [CrossEncoder loading and inference](https://sbert.net/docs/package_reference/cross_encoder/model.html).
- [faster-whisper local models and lazy transcription](https://github.com/SYSTRAN/faster-whisper).


## P3：PostgreSQL + pgvector 迁移与完整性（2026-09-20）

生产检索默认只有 PostgreSQL/pgvector，一个数据库保存权威资料与可重建投影。
`retrieval_generations` 保存完整语义身份，`retrieval_entries` 保存向量、词频和范围。
不是仅比较维数；同维模型、切分、解析、前缀或词法合同变化会产生新代次。
发布替换、块状态及文档索引指纹同事务提交；模型调用发生在事务外。
源资料在解析/Embedding期间改变时，旧任务不能发布；删除与替换按文档行锁串行。
查询在排名与BM25语料统计之前复核文档、块和文件的用户、状态与代次；
私有会话附件不进入共享索引。召回后的正文授权复核继续保留。

### 搜索质量和资源边界

稠密检索先采用**有界精确搜索**，不是给小型单机默认叠加HNSW参数。
词法路径使用版本化中文单字/双字和保留技术标识符的BM25；它不是PostgreSQL
`ts_rank`冒充BM25，也不声称与原Milvus/jieba分词等价。范围内统计不混入其他用户。
保留既有BGE Embedding/重排作为对照；本次模型权重与阈值不变。
语义质量是否无回退必须用原有带证据标注的数据集对照，数据库正确性测试不能代替它。
`RAG_INDEX_STATEMENT_TIMEOUT_MS`、`RAG_INDEX_LOCK_TIMEOUT_MS`、文档块数、查询字节和
返回条数都有边界；超过容量明确报不可用，不把未完成查询当作没有资料。

### 现有数据库与旧索引

Compose的数据库基于原 `postgres:15.18-alpine`，只添加从官方精确提交
`8ee86c96f0fd72390f890aa8a336fda6d3ab4c6c` 构建的pgvector0.8.6。保留原 `pgdata`
卷和PostgreSQL主版本/系统库家族，不自动搬到Debian或新空卷。
升级前备份PostgreSQL和原始文件；暂停API/Worker/Beat后统一升级代码与数据库，
不支持旧Milvus Worker和新Worker混跑。`0056`不调用模型、不清空原始资料，也不读取
或删除旧Milvus卷；旧outbox行只改分派类型，保留身份和幂等键。
移除的是Milvus/etcd/专用MinIO的默认运行服务，不是用户旧磁盘数据。
不要使用 `docker compose down -v` 当作升级命令。

已发布的旧索引不会因为迁移建表就冒称可查询；后台代次对账会将可重建资料送入
既有outbox。操作员也可先运行只读计划：

```bash
python scripts/reingest_hybrid.py --limit 100
python scripts/reingest_hybrid.py --user 1 --limit 100
# 核对范围后才明确执行；这会加载本地Embedding，或按当前配置调用远端模型。
python scripts/reingest_hybrid.py --user 1 --limit 100 --execute
# 使用计划返回的游标继续有限批次；不支持清空全部索引的 --drop。
python scripts/reingest_hybrid.py --user 1 --after <document-id> --limit 100 --execute
python scripts/consistency_scan.py
```

手动重建适用于已有规范块；没有任何解析块的资料仍通过正常导入流程重试，
不把空资料伪装成一次成功恢复。旧外部索引与快照保留到质量对照和回退验收之后。
已有投影数据时降级迁移要求先备份，不自动销毁；迁移失败保持原始资料。

官方依据：pgvector的精确距离、不同维数列、Docker和构建说明
https://github.com/pgvector/pgvector ；Python/SQLAlchemy类型
https://github.com/pgvector/pgvector-python ；事务与行锁
https://www.postgresql.org/docs/current/explicit-locking.html 。
