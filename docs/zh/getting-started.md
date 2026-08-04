# 启动指南

## 1. 先确定运行边界

自己运行源码、学习或二次开发请选择 Community。Cloud 是面向最终用户的托管
产品策略，需要运营方提供真实云基础设施；根目录 Compose 属于 Community。

本地有且只有两条受支持路径：宿主开发模式和完整容器模式。不要在同一份代码、
同一组端口上同时运行两种模式。

## 2. 路径 A：宿主开发模式

适合阅读、调试和修改源码。需要：

- Python 3.11–3.13，并已激活独立虚拟环境；
- Node.js 20+；
- Docker Compose v2。

首次安装：

```powershell
pwsh ./scripts/setup.ps1
```

脚本会另外询问 Community 模型方案：轻量远程、本地/混合 CPU 或本地/混合
CUDA。例如，本地 CPU 的无人值守安装使用
`pwsh ./scripts/setup.ps1 -ModelProfile local-cpu`；可选值为 `remote`、
`local-cpu` 和 `local-cuda`。

```bash
bash ./scripts/setup.sh
```

例如，本地 CPU 的无人值守安装使用
`COMMUNITY_MODEL_PROFILE=local-cpu bash ./scripts/setup.sh`，可选值同上。

安装时选择 Community。脚本会在缺少 `.env` 时创建配置，安装依赖，生成缺失的
`SECRET_KEY`，启动 PostgreSQL、Redis、MinIO 和 Milvus，执行数据库迁移，并
通过 `npm ci` 安装前端依赖。

日常启动：

```powershell
.\scripts\start.ps1
```

```bash
bash ./scripts/start.sh
```

启动器会在一个终端中运行 Uvicorn、不同负载的 Celery Worker、Celery Beat 和
Vite。浏览器打开 `http://localhost:5173`，按 `Ctrl+C` 停止宿主进程。默认终端
只显示关键状态，完整输出仍保存在 `data/logs`；排错时可在 PowerShell 添加
`-VerboseLogs`，或在 Bash 添加 `--verbose-logs`。

## 3. 路径 B：完整容器模式

适合运行打包后的 Community，不在宿主机启动 Python、Celery 或 Node 进程。

```powershell
Copy-Item .env.community.example .env
python scripts/generate_secret.py
```

将输出写入 `.env` 的 `SECRET_KEY`，并填写部署方内部模型密钥及需要的可选服务
密钥，然后运行：

```bash
docker compose --profile full up -d --wait
```

容器默认只安装远程供应商所需依赖；本地 CPU 模型设置 `APP_EXTRAS=local`，
NVIDIA 部署设置 `APP_EXTRAS=local,cuda` 后重新构建。

浏览器打开 `http://localhost`。完整模式会启动前端、API、五类 Worker、调度器
和全部基础设施；一次性的 `migrate` 服务会先执行 `alembic upgrade head`。

查看和停止：

```bash
docker compose --profile full ps
docker compose --profile full logs -f api worker-turns
docker compose --profile full down
```

普通 `down` 会保留数据卷；不要随意添加 `--volumes`，它会永久删除数据库和
基础服务数据。

> `0.1` Community 版本重新建立了迁移基线。仅由未发布开发迁移
> `0001_baseline` 至 `0051` 创建的旧数据库不能原地升级；请先导出需要保留的
> 数据，再删除旧开发数据卷并重新初始化。自 `0.1` 正式版起会保持连续迁移链。

## 4. 模型

Community 可以使用远程 API、全本地模型，也可以按能力混合。远程方案不会下载
数 GB 模型；选择本地 CPU/CUDA 后，安装脚本会安装 `local` extra 并自动进入
模型向导。之后也可以单独再次运行：

```bash
python scripts/init_models.py
```

向导可以分别选择 Embedding、Reranker、Whisper、说话人分离和 Docling；每项
都可以使用推荐模型或输入兼容的 Hugging Face 仓库。选择结果（包括 Embedding
维度）会写入 `.env`，只下载实际启用的项目。自动化环境使用
`--non-interactive`、`--only ROLE` 或 `--dry-run`，不会等待输入。

所有模型权重统一位于 `data/cache/models`，库元数据和断点续传状态也只保存在
`data/cache` 下，不会写入用户目录。宿主开发和完整容器这两种启动方式共用这一
受管缓存。

运行时文件统一放在被 Git 忽略的 `data/`：模型和字节码缓存在 `cache/`，日志在
`logs/`，Celery 状态在 `runtime/`，对象存储降级文件在 `storage/`，大工具结果
在 `agent-results/`，文档和音频临时文件在 `tmp/`。临时文件超过 24 小时、宿主
启动日志超过 14 天以及已经删除会话遗留的工具结果会由每日任务清理；
`metrics.jsonl` 达到 50 MiB 后只保留一个备份。模型缓存下载成本高，不会自动
删除，应在停止 Worker 后由部署者按模型目录手动清理。

Cloud 的 Embedding、Reranker、ASR 和说话人分离由运营方提供，不会暴露给普通
用户配置。

## 5. 首次业务验证

1. 注册并验证邮箱；本地故意关闭 SMTP 时，从后端输出读取验证码。
2. 退出后在登录页通过“忘记密码”验证邮箱并重置密码。
3. 选择最终回答模型，并按需保存个人 LLM API Key；内部模型由部署方提供。
4. 上传简历和 JD，完成一次模拟面试并查看复盘。
5. 添加可选 Skill 和 MCP，并检查会话权限。

更完整的持久化、升级、模型和 MCP 说明见
[Community 部署文档](../deployment/community.md)。修改源码前请阅读
[代码库结构与依赖方向](../architecture/codebase.md)。
