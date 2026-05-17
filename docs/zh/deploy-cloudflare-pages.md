# Cloudflare Pages — 前端部署

> **这是进阶 / 可选步骤。** **本地使用根本不需要 Cloudflare。** `scripts/start.ps1`
> 本地开发、Tailscale 局域网共享、用 `docker compose` 部署到自己服务器 ——
> 全都不需要任何 Cloudflare。
>
> **只有同时想要这三件事**才需要 Cloudflare Pages：
>
> 1. 公网 hostname（任何人都能访问）
> 2. 免费 SSL + 全球 CDN 加速静态前端
> 3. 前端零成本托管（个人规模约 $0/月）
>
> **你仍然需要一台后端服务器**（自己的 VPS、云主机、任何能被 Cloudflare
> 访问到的公网 IP + 域名）。Cloudflare Pages 在这里只托管前端静态 `dist/`
> 文件，前端跨域调用你自己的后端。
>
> 如果只是想演示给朋友、没有公网后端，**用 [Tailscale](https://tailscale.com/)
> 就行** —— 把笔记本的 Tailscale hostname 给他们，完全不需要 Cloudflare。

---

本项目的 React SPA 适合直接挂 Cloudflare Pages。后端继续放原处（你的 VPS / docker 主机），Pages 只服务静态 `dist/` 产物，并把 API 调用跨域转发到后端。

## 一次性配置

### 方案 A — GitHub 关联（推荐：单人 / 小团队）

1. 把项目推到 GitHub
2. Cloudflare 控制台：**Workers & Pages → Create → Pages → Connect to Git**，选仓库 + `main` 分支
3. 构建配置：
   - **Framework preset**：`Vite`
   - **Build command**：`cd frontend && npm ci && npm run build`
   - **Build output directory**：`frontend/dist`
   - **Root directory**：留空（项目根）
   - **Node version 环境变量**：`NODE_VERSION=20`
4. **环境变量**（Settings → Environment variables，选 "Production" 或两环境都加）：
   ```
   VITE_API_BASE              https://api.your-domain.com/api/v1
   VITE_SENTRY_DSN            <你的 Sentry DSN 或留空>
   VITE_SENTRY_ENVIRONMENT    prod
   VITE_SENTRY_TRACES_SAMPLE  0.1
   ```
5. 触发首次部署。后续 push 到 `main` 自动部署。

### 方案 B — `wrangler` CLI（手动 / CI）

```bash
npm i -g wrangler
cd frontend
npm ci && npm run build

# 第一次：选项目 / 创建项目
wrangler pages deploy dist --project-name interview-copilot

# 后续部署
wrangler pages deploy dist --project-name interview-copilot --branch main
```

`wrangler.toml` 故意没提交 — 纯 Pages 项目用控制台 / CLI 参数就够了。

## 自定义域名

在项目的 **Custom domains** 标签里加 `app.your-domain.com`。Cloudflare 通过 Universal SSL 自动签 TLS 证书。

如果根域 `your-domain.com` 也在 Cloudflare DNS，加一个 `CNAME @ app.your-domain.com.cdn.cloudflare.net` flattening 让 root 域也能用。

## CORS — 后端必须放行 Pages 域名

把 Pages 的 preview + production 域名加到后端 `.env`：

```ini
CORS_ORIGINS=https://app.your-domain.com,https://interview-copilot.pages.dev
```

（如果你想让 PR-preview URL 也工作，需要 wildcard 比如 `https://*.interview-copilot.pages.dev`。FastAPI 的 `CORSMiddleware` 不支持 `allow_origins` 里写 wildcard — 需要改成 `allow_origin_regex=r"https://.*\.interview-copilot\.pages\.dev"`，在 `backend/app/main.py` 里改。）

## 缓存 + 头处理

仓库已经自带：

- `frontend/public/_headers` — 哈希命名的资源长缓存、HTML 不缓存、安全头（X-Frame-Options / nosniff / Referrer-Policy / Permissions-Policy）
- `frontend/public/_redirects` — `/* → /index.html 200` SPA 回退

Vite 构建时这两个文件自动复制到 `dist/`，Pages 会识别。**控制台不需要再配缓存规则。**

## 成本与限额（免费版）

- 500 次构建 / 月
- 不限带宽 + 请求数
- 每个项目 100 个自定义域名
- 单文件最大 25 MiB（我们项目最大文件是 Inter 可变字体 ~1.2 MB，远低于上限）

对中小团队，免费版基本够用永久。$20/月的 Pro 主要是更多并发构建 + 图像变换。

## 可观测建议

想看每条资源路径的流量 / 缓存命中率：控制台 → 项目 → **Analytics**。默认 dashboard 已经按 region 显示边缘 P50/P95 延迟 — 这就是验证「全国 200 ms → 30 ms」的方式（部署前后对比）。
