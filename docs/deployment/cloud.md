# Cloud 部署配置帮助

Cloud 需要运营方提供数据库、队列、模型、文件存储、域名和邮件服务。仓库根目录的 Compose 用于 Community 本地运行，不是一键生产 Cloud 部署。

## 配置准备

```bash
cp .env.cloud.example .env
```

按模板填写：

- `ENVIRONMENT=production`、独立且稳定的 `SECRET_KEY`；
- PostgreSQL 连接和 pgvector 扩展、Redis、私有文件存储或明确配置的 S3；
- TLS 域名、`CORS_ORIGINS` 和可信代理；
- 内部模型、Embedding、Reranker 与语音服务的有效凭据；
- 真实认证与邮件服务配置。

第三方 OAuth 连接需分别填写对应提供商的客户端配置、回调地址和凭据存储。未配置可用凭据存储的连接保持不可用。公开部署不要启用本地 stdio MCP。

## 启动和更新

在部署环境构建后端和前端镜像，配置持久化目录和依赖服务。先备份现有数据，再用相同版本镜像执行：

```bash
alembic upgrade head
```

启动 API、前端、各 Worker 和调度服务后，通过对外地址检查 `/api/v1/health/ready`，并实际验证登录、资料上传、回答和录音处理。服务环境中的数据库与模型地址必须能够被所有相应进程访问。

## 备份与恢复

停止写入后，按所配置的文件存储备份数据库和资料：

```bash
python scripts/backup.py create --output /secure/backups --include-objects
```

恢复到预先创建的目标数据库和空文件存储：

```bash
python scripts/backup.py restore /secure/backups/<timestamp> --target-database-url postgresql://.../restore_target --restore-objects
```

数据库和文件恢复是分别执行的步骤。保留原始密钥和备份，先验证恢复结果，再切换访问入口。录音、个人资料和服务密钥不要放入镜像或源码仓库。
