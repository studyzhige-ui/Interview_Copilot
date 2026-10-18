# Interview Copilot

本地运行的求职与面试助手，支持岗位管理、简历与 JD 资料、模拟面试、录音复盘和对话助手。

## 启动方式

首次使用建议选择完整 Docker 容器模式。Windows 使用 Docker Desktop 的 Linux 容器；宿主运行模式使用 Linux 或 WSL2。

1. 安装 Git、Docker 和 Docker Compose v2，克隆仓库并进入项目目录。
2. 复制配置模板。Windows PowerShell：

```powershell
Copy-Item .env.community.example .env
```

Linux / WSL2：

```bash
cp .env.community.example .env
```

3. 编辑 `.env`：生成并填写稳定的 `SECRET_KEY`，修改 `POSTGRES_PASSWORD` 并同步 `DATABASE_URL`；填写 `DEEPSEEK_API_KEY`，以及默认检索服务需要的 `SILICONFLOW_API_KEY`。
4. 启动：

```bash
docker compose --profile full up -d --build --wait
```

打开 **http://localhost**。首次构建需要联网下载镜像和依赖；默认轻量镜像不包含本地语音模型，录音功能需按部署指南另行准备。

## 使用帮助

- [完整启动指南与常见故障](docs/getting-started.md)
- [功能使用说明](docs/usage.md)
- [Community 配置、模型、数据备份与升级](docs/deployment/community.md)
- [本地模型安装和启动](docs/deployment/local-first.md)
- [Windows 桌面应用帮助](desktop/README.md)
- [Cloud 部署配置](docs/deployment/cloud.md)

停止服务使用 `docker compose --profile full down`，此命令保留数据卷。不要用 `down --volumes` 代替日常停止。

`.env`、密钥、录音和用户资料只保存在本地，不要提交。开发、架构、评测与实施记录不随 main 分发；程序运行模板和第三方许可仍随源码保留。
