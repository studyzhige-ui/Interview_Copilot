# 启动指南

## 1. 选择版本

自部署、阅读源码或本地开发请选择 Community；面向普通用户部署 Web 产品请选择
Cloud。

```powershell
Copy-Item .env.community.example .env
# 或
Copy-Item .env.cloud.example .env
```

生成安全密钥：

```bash
python scripts/generate_secret.py
```

将输出写入 `.env` 的 `SECRET_KEY`。

## 2. 自动安装

Windows：

```powershell
pwsh ./scripts/setup.ps1
```

Linux/macOS：

```bash
bash ./scripts/setup.sh
```

脚本会安装依赖、启动本地基础设施并执行数据库迁移。

手动安装依赖时，Cloud 使用：

```bash
python -m pip install -e ".[dev]"
```

Community 使用：

```bash
python -m pip install --extra-index-url https://download.pytorch.org/whl/cu129 -e ".[community,dev]"
```

## 3. 模型

Cloud 模板默认使用远程 Embedding、Reranker 和 ASR。相关密钥属于平台运营方，
不会出现在普通用户设置页。

Community 模板默认使用本地 BGE、WhisperX 和 Pyannote。首次下载：

```bash
python scripts/init_models.py
```

Community 也可以把 `*_PROVIDER` 改为云端 API。版本边界和模型运行位置互相独立。

## 4. 启动

后端：

```bash
uvicorn app.main:app --app-dir backend --reload --port 8080
```

任务 Worker（以下三条命令分别在三个终端运行；也可直接使用启动脚本）：

```bash
celery -A app.worker.celery_app.celery_app worker --workdir backend --pool=solo --queues=default,pipeline,transcription
celery -A app.worker.celery_app.celery_app worker --workdir backend --pool=threads --concurrency=2 --queues=turns
celery -A app.worker.celery_app.celery_app beat --workdir backend
```

前端：

```bash
cd frontend
npm run dev
```

打开 `http://localhost:5173`。

## 5. 验证

1. 注册账户。
2. 选择最终回答模型，并按需保存个人 LLM API Key；内部规划模型由部署方提供。
3. 上传简历与 JD。
4. 完成一次模拟面试。
5. 添加可选 Skill 和 MCP。
