# 启动指南

## 运行前准备

自行运行请选择 Community。安装 Git、Docker 和 Docker Compose v2，并进入克隆后的项目目录。

Windows 使用已启动的 Docker Desktop，切换到 Linux 容器。宿主 Python/Celery 模式需在 Linux 或 WSL2 中运行；不要在原生 Windows 上运行后端。

先检查：

```bash
docker info
docker compose version
```

首次启动需联网下载基础镜像、依赖和选定的模型。下载时间和所需磁盘空间取决于使用远程 API 还是本地模型。

## 方式一：完整容器（推荐）

Windows PowerShell：

```powershell
Copy-Item .env.community.example .env
```

Linux / WSL2：

```bash
cp .env.community.example .env
```

编辑 `.env`，至少确认：

| 配置 | 如何填写 |
| --- | --- |
| `SECRET_KEY` | 唯一、稳定的随机密钥，至少 32 个字符；已有数据时不要随意重置 |
| `POSTGRES_PASSWORD` | 设置自己的数据库密码，并同步修改 `DATABASE_URL` |
| `DEEPSEEK_API_KEY` | 默认内部模型所用的部署密钥 |
| `SILICONFLOW_API_KEY` | 默认 Embedding 与 Reranker 所用密钥；改用其他服务时填写对应配置 |
| `AUTH_PROVIDER` | 默认 `local`；注册后按界面完成验证 |

可以使用已安装的 Python 生成密钥：

```bash
python scripts/generate_secret.py
```

若宿主没有 Python，也可运行一次临时 Python 容器生成：

```bash
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将生成值写入 `.env`，不要把输出发到公开渠道。启动：

```bash
docker compose --profile full up -d --build --wait
```

打开 **http://localhost**。启动过程会等待依赖健康，并通过 `migrate` 服务执行数据库迁移。默认数据库使用 PostgreSQL/pgvector，不需要安装 Milvus；文件默认保存在私有的 `data/storage`。

默认轻量镜像没有 WhisperX、BGE/Pyannote 本地模型依赖。需要录音或本地模型时，先完成[本地模型部署](deployment/local-first.md)。

日常查看及停止：

```bash
docker compose --profile full ps
docker compose --profile full logs --tail 100 api worker-turns worker-transcription worker-pipeline migrate
docker compose --profile full down
```

`down` 保留数据库卷和本地资料；`down --volumes` 会删除数据卷，不能用于日常停止。

## 方式二：Linux / WSL2 宿主运行

需要 Python 3.11–3.13、Node.js 24、Docker Compose v2 和已激活的 Python 虚拟环境。在 Linux / WSL2 终端执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
bash scripts/setup.sh
```

按提示选择 Community 和模型方案：`remote`、`local-cpu` 或 `local-cuda`。脚本安装依赖、创建配置、启动数据库和 Redis、执行迁移并安装前端依赖。本地模型方案还会进入模型配置向导。

以后每天启动：

```bash
source .venv/bin/activate
bash scripts/start.sh
```

打开 **http://localhost:5173**。按 `Ctrl+C` 停止前台服务；需要停止数据库和 Redis 时执行 `bash scripts/stop.sh`。完整日志保存在 `data/logs`，实时详细输出使用 `bash scripts/start.sh --verbose-logs`。

## 第一次使用

1. 注册或登录。默认本地认证未配置 SMTP 时，从 API 日志中读取验证邮件的验证码；真实邮件需配置 SMTP。
2. 在设置中选择回答模型，填写个人 API Key（如该模型需要）。个人回答模型配置和部署所需的内部模型配置分别填写。
3. 上传简历或 JD，等待处理完成后再开始提问或模拟面试。
4. 使用录音前准备语音依赖和模型，并授予浏览器麦克风权限。

更多操作见[使用帮助](usage.md)。

## 常见问题

- **Docker 无法连接**：启动 Docker Desktop 或 Docker 服务，确认 `docker info` 成功；Windows 检查是否为 Linux 容器。
- **80 或 5173 端口被占用**：先停止占用端口的应用，确认没有同时运行两种启动方式。
- **首次构建超时**：检查镜像仓库、Python/npm 源和模型下载网络；查看 Compose 日志后重新执行启动命令。
- **页面打开但无法回答**：检查个人回答模型配置，以及 `.env` 中的内部模型凭据；修改环境配置后重新运行 Compose `up` 命令。
- **资料处理失败**：查看 `worker-pipeline` 日志，检查检索服务密钥；本地模型用户检查模型文件和推理服务。
- **语音功能不可用**：检查 `worker-transcription`、本地模型依赖及麦克风权限。远程浏览器录音需 HTTPS 或浏览器允许的本机地址。
- **没有验证邮件**：默认本地模式先查看 API 日志；使用外部认证服务时按服务配置检查邮件投递。
- **旧数据库启动失败**：先备份并保留完整错误，核对迁移版本；不要以删除卷或重置密钥作为通用修复。
