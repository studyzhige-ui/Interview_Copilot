# Local-first deployment and verification boundaries

Status: evaluator, local-asset policy, pgvector and the local RAG inference
broker are implemented. Real-time audio and all-model scheduling remain open.
Do not interpret this guide as a tested one-command installation of all future models. No production data is
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


## P2：共享本地 RAG 推理服务（2026-09-20）

本批把本地 Embedding 和重排从 API/Celery 进程移到一个独立服务；
`EMBEDDING_PROVIDER=local` 和 `RERANKER_PROVIDER=local` 不再在应用中加载权重。
现有模型目录只读复用，不下载新模型、不启用远端 fallback。普通 CPU tokenizer
仍可本地加载，但强制 `local_files_only`，不加载 Embedding 权重。

这是 **P2 的已接入子集**：支持 SentenceTransformer / CrossEncoder（当前 BGE 基线）。
不是声称已接入 Qwen ASR、CosyVoice、ForcedAligner、说话人和 Docling，也不是实时媒体服务。
缺少模型不会妨碍代码回归；实际权重、GPU内核、精度和显存峰值在用户实机另验。

### 明确准备、启动与诊断

业务环境与本地 RAG ML 环境分开。ML 环境需要与模型相容的 Torch、Transformers、
SentenceTransformers；不要把 WhisperX/Qwen/vLLM 的不同依赖强行装进同一个环境。
可复用已有本地模型与已验证的 ML 环境。这里不声称当前旧 `[local]` extra 可作为
将来所有音频模型的统一安装锁；完整环境锁与语音安装入口仍是后续交付项。

```bash
# 使用业务 Python 做结构/哈希检查，只写一个新的 owner-only config.json；不加载权重。
# 运行目录选 Linux 文件系统，保持 Unix socket 路径短于 100 字节。
python scripts/prepare_local_inference.py \
  --python /home/your-user/venvs/local-rag/bin/python --device cuda \
  --runtime-dir /home/your-user/.ic-inference \
  --model-root /mnt/d/Projects/Python/Interview_Copilot/data/cache/models

# 将命令输出的 LOCAL_INFERENCE_SOCKET 合并到原 .env，不替换密钥/数据库配置。
# 前台运行独立 broker；模型由它按需启动，在独立解释器中驻留。
python scripts/run_local_inference.py --config /home/your-user/.ic-inference/config.json

# 另一个终端：只读取队列/驻留/聚合计数，不加载模型、不返回输入文本。
python scripts/run_local_inference.py --config /home/your-user/.ic-inference/config.json --status
```

准备命令拒绝覆盖已有配置；改变模型需停止旧服务、核对生成的新配置再切换。
Unix socket 与父目录要求 owner-only；两端检查同 OS UID。应用账户权限和账本仍在
现有应用层，这个 socket 不向浏览器开放，不接受任意 Python 模块名或模型路径。
容器部署要将同一 socket 目录挂载到调用者，并匹配 UID；未配置时明确不可用，
不会偷偷创建一套进程或云端调用。默认 Compose 不会替用户自动安装 ML 环境。

### 生命周期、资源与错误

一个确定性调度 lane 串行执行请求；交互查询优先，后台任务通过等待老化获得机会。
当前队列最多 16 个未完成任务，连接最多 24 个，文本与消息大小、加载、执行、
读取、写入和关闭均有边界。模型可在多个请求间复用，空闲到期或预约容量不足时，
先停止并回收旧进程，再释放预约。默认 CUDA 预约总额 12000 MiB，Embedding 5000、
重排 3000。**这些是准入估算，不是硬件测量、硬显存隔离或“16GB一定够用”的承诺。**
CPU模型不占CUDA预约；系统外的GPU程序与尚未接入的模型不受这个调度器控制。

取消排队任务不会执行；取消已开始的任务会清理整个已拥有的进程组，回收后才调度下一项。
父服务突然死亡时，Linux parent-death signal终止直接模型子进程；这不是对任意
第三方子孙进程或恶意native代码的安全沙箱。不得将当前直接模型进程合同冒用到
尚未集成的vLLM多进程执行。网络关闭由SDK离线选项和Python审计辅助，强隔离需OS配置。

连接前失败/明确未开始与发送后未知分开；应用账本只对明确拒绝释放额度。
重排分批时，首批已运行后下一批被拒绝，也不会退还整次操作或静默切换。
连接关闭不表示“没有计算过”；服务不提供持久响应回放或跨重启exactly-once承诺。
主程序仍使用原消费作用域，broker不接收DeepSeek密钥、数据库地址、代理和调用者PYTHONPATH。

### 输入与索引语义

Embedding 使用显式查询/文本前缀、归一化向量和真实 tokenizer 长度检查；
超长输入拒绝，不让库的隐式截断吞掉证据。模型维数和响应身份必须匹配。
重排返回模型原始相关性分数，**不是用户十分制成绩**，不会夹紧到0–10。
适配合同、前缀、token上限和已知模型revision进入索引身份；旧代次保留，但要使用
P3的有界重建路径生成新代次，不能把不同向量语义混写。旧未固定revision的资产
仍明确属于未固定来源，不伪造权重身份；正式质量对照需固定资产版本。

### 已验证与尚未验证

新增测试执行了真实Unix连接和真实新Python进程，模型使用测试专属协议替身，
生产代码没有测试模型开关。测试覆盖复用、私密环境、错误/过大输出、日志洪泛、
断连/重复取消、队列期限、后台老化、驻留回收、父进程强制退出及RAG工厂实际接入。
SDK模型逻辑另外用小型替身检查前缀、长度和结果形状。没有真实权重、准确率或GPU成绩。

官方接口参考（2026-09-20复核）：
- Python asyncio streams / subprocess：https://docs.python.org/3.13/library/asyncio-stream.html
- PyTorch CUDA进程限制：https://docs.pytorch.org/docs/stable/notes/multiprocessing.html
- SentenceTransformer：https://sbert.net/docs/package_reference/sentence_transformer/model.html
- CrossEncoder：https://sbert.net/docs/package_reference/cross_encoder/model.html
- Linux parent-death语义：https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html


## P2 音频扩展：有限片段 Qwen 转写与独立对齐（2026-09-20）

本节扩展前述 RAG broker，同一私有 socket 和同一调度 lane 现在可配置四个角色：
Embedding、重排、Qwen Transformers 转写、Qwen ForcedAligner。它是有限片段的
生产调用能力，**不是 vLLM 连续流式 ASR、WebRTC 或完整录音复盘切换**。
TTS、说话人、OCR尚未纳入这个资源管理器；不能从四角色测试外推这些模型已接入。

### 接口与本地资产

使用单独的音频 Python 环境，参考官方 `qwen-asr==0.0.6` 及其兼容依赖。不要将其
固定的 Transformers/Accelerate/vLLM 依赖装进业务环境或覆盖已有 RAG 环境。
本轮不提供“已在5060Ti上验收”的环境锁，不下载权重，也不启动付费服务。
目标权重是 `Qwen/Qwen3-ASR-1.7B`（也支持明确配置0.6B）和
`Qwen/Qwen3-ForcedAligner-0.6B`；二者使用独立进程，可分别驻留/回收。

在最终本机验收阶段，有完整权重和独立音频环境后，再准备新的配置目录：

```bash
python scripts/prepare_local_inference.py \
  --python /home/your-user/venvs/local-rag/bin/python \
  --audio-python /home/your-user/venvs/qwen-audio/bin/python \
  --device cuda --runtime-dir /home/your-user/.ic-inference-audio \
  --model-root /mnt/d/Projects/Python/Interview_Copilot/data/cache/models
```

已有配置仍拒绝覆盖，切换前停止旧 broker 并核对模型身份。ASR默认预约7000MiB、
对齐3500MiB；总CUDA预约默认12000MiB。**这是保守准入配置而非实测峰值**，CPU模型
不占CUDA预约，也不因为其预约数值超过CUDA容量而被拒绝。加入音频角色不改变现有
RAG绑定hash，不应为无语义变化的Embedding额外重建索引。

`local_qwen_asr` 已接入通用文件转写和模拟面试的录音回答入口。只有明确配置
`TRANSCRIPTION_PROVIDER=local_qwen_asr` 与相匹配的 `TRANSCRIPTION_MODEL` 才会选用，不能由服务失败触发
静默切换。**上传面试的证据入口仍使用现有WhisperX合同**：Qwen文本结果没有说话人，
不得冒充完整词级复盘依据。待独立说话人/角色与新证据编排接入后再统一默认；本批
没有把未写完的部分包装成用户侧模型验收，也没有要求现在下载模型。

### 有界音频与错误语义

应用在验证资料所有权后打开本地普通文件，固定文件描述符；FFmpeg只使用许可的
本地协议及常见音视频demuxer，不接受网络URL或播放列表引用其他资料。输出以
16kHz、单声道PCM16分块，每次最多30秒；不一次物化整场音频或输出。输入字节、
解码总时长、读取期限和最终文字总量有上限。前段有效、后段损坏仍是失败，
不是返回前段文字冒充完整转写；源文件处理中变化也明确失败。

每个IPC音频包包含样本数、采样率、编码和SHA-256，不传任意文件路径或URL给ML子进程。
ASR只返回文字与语言；对齐另收原文字，核对词/字覆盖和时间界限，不允许改写原文。
零长/缺失对齐明确标为未对齐，不编造时间、置信度、说话人或“文字已核实”。
固定分块存在跨块语义边界，因此本批不声称解决长音频的高质量接缝/分段策略。

短回答走交互优先级，文件转写/对齐默认后台优先级。排队期限到达时立即移除并明确
拒绝，不等前面的长任务完成，更不能超时后继续偷偷执行。执行后的未知状态和
结算确认丢失不降格为普通可重试服务不可用；录音回答API返回409，不自动换提供者
重发。多段转写已执行部分后再遇到拒绝，整项消费保守保留，不退还已执行部分。

取消/早退会回收拥有的FFmpeg进程组与文件句柄。模型清理若失败，broker进入故障
停止接单，保留未确认释放的预约，不在资源状态未知时加载下一模型。
这些是故障与准入约束，不是对恶意本地库或所有FFmpeg原生漏洞的完整OS沙箱。

### 验证与官方依据

工程测试使用合成PCM、真实FFmpeg、真实Unix连接和新Python子进程；模型数学使用
测试专属替身，生产代码没有假模型开关。覆盖损坏/超限音频、跨块失败、取消回收、
文本与时间戳校验、进程复用、配置绑定、排队过期和资源清理失败。CI显式检查FFmpeg
可用，不把未执行的解码测试计为通过。Qwen权重准确率、设备延迟和显存峰值未实测。

官方接口（2026-09-20核对）：
- Qwen API/限制：https://github.com/QwenLM/Qwen3-ASR
- 依赖版本：https://github.com/QwenLM/Qwen3-ASR/blob/main/pyproject.toml
- FFmpeg协议与demuxer选项：https://ffmpeg.org/ffmpeg-formats.html
- Python有界pipe与取消清理：https://docs.python.org/3.13/library/asyncio-subprocess.html
