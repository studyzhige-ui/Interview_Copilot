# 本地模型准备与启动

本页适用于已完成[首次启动配置](../getting-started.md)的 Community 用户。本地模型需要相应依赖、可用权重和足够内存或显存；仅修改模型名称不能完成安装。

## Linux / WSL2

首次安装时运行 `bash scripts/setup.sh`，选择 `local-cpu` 或 `local-cuda`，按向导准备模型。已有环境可重新运行模型向导：

```bash
python scripts/init_models.py
```

配置本地 Embedding、Reranker 或说话人分离时，准备并启动本地推理服务。以下 Python 路径和模型目录需要替换为实际 Linux 路径：

```bash
python scripts/prepare_local_inference.py --python /home/your-user/venvs/local-ml/bin/python --device cpu --runtime-dir /home/your-user/.ic-inference --model-root /path/to/Interview_Copilot/data/cache/models
python scripts/run_local_inference.py --config /home/your-user/.ic-inference/config.json
```

将准备命令输出的 `LOCAL_INFERENCE_SOCKET` 合并到现有 `.env`，不要覆盖原密钥和数据库设置。需要单独语音环境时，准备命令可用 `--diarization-python` 指定它。

运行目录应在 Linux 文件系统中；不要把 Unix socket 放到 Windows 挂载目录。准备命令拒绝覆盖已有配置。更换模型前停止服务，准备新的配置并核对后切换。

检查状态：

```bash
python scripts/run_local_inference.py --config /home/your-user/.ic-inference/config.json --status
```

另一个终端使用已激活的业务环境执行 `bash scripts/start.sh`。

## 完整容器 CPU 模式

在 `.env` 中设置：

```dotenv
APP_EXTRAS=local
EMBEDDING_PROVIDER=local
RERANKER_PROVIDER=local
TRANSCRIPTION_PROVIDER=local_whisperx
LOCAL_INFERENCE_SOCKET=/app/data/runtime/local-inference/worker.sock
```

准备镜像、权重与推理配置：

```bash
docker compose build api
docker compose run --rm api python scripts/init_models.py
docker compose run --rm --no-deps local-inference python scripts/prepare_local_inference.py --python /opt/venv/bin/python --device cpu --runtime-dir /app/data/runtime/local-inference
docker compose --profile local up -d --wait local-inference
docker compose --profile full --profile local up -d --build --wait
```

首次创建的配置应保持稳定，不要对运行中的推理服务重复执行准备命令。CUDA 需要匹配的 NVIDIA 驱动、容器 GPU 访问权限和本地 CUDA 依赖，不能只把 `--device` 改为 `cuda`。

## 语音和模型故障

语音功能需保持 `worker-transcription` 运行。CPU 长录音处理可能较慢；先查看原任务状态，不要重复上传。缺少权重、模型依赖或推理服务时，按日志提示准备后重试。

模型权重位于 `data/cache/models`，下载中间状态位于 `data/cache`。删除缓存前停止相关服务，只删除确认不再使用的模型目录。

更换 Embedding 模型或维度后，需要重新处理资料索引。现有资料的索引操作可先查看有限批次计划：

```bash
python scripts/reingest_hybrid.py
```

确认范围及模型调用成本后，才添加 `--execute` 执行，并使用返回的游标继续。不要通过删除用户原始资料来重建检索。
