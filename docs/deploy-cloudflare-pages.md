# Cloudflare Pages — Frontend Deployment

> **This is advanced / optional.** You do NOT need Cloudflare to run or
> use Interview Copilot. Local dev (`scripts/start.ps1`), Tailscale
> share over your home LAN, and standard `docker compose` production
> deploys all work without it.
>
> **Reach for Cloudflare Pages only if you want all three of:**
>
> 1. A public hostname (anyone on the internet can hit it)
> 2. Free SSL + global CDN for the static frontend bundle
> 3. Zero-cost hosting for the SPA (~$0/month for personal-scale traffic)
>
> **You still need a backend somewhere** (your VPS, a docker host on a
> cloud VM, anything with a public IP and a domain that Cloudflare can
> reach). Cloudflare Pages here only hosts the frontend's static
> `dist/` files. The frontend talks to your backend cross-origin.
>
> If you don't have a public-facing backend and just want to demo the
> project to friends, **use [Tailscale](https://tailscale.com/) instead**
> — point them at your laptop's Tailscale hostname, no Cloudflare needed.

---

This project's React SPA deploys cleanly to Cloudflare Pages. The
backend stays where it is (your VPS / docker host) — Pages only serves
the static `dist/` output and forwards API calls cross-origin to your
backend.

## One-time setup

### Option A — GitHub-connected (recommended for solo / small team)

1. Push this repo to GitHub if you haven't already.
2. In Cloudflare dashboard: **Workers & Pages → Create → Pages →
   Connect to Git**. Pick the repo + `main` branch.
3. Build settings:
   - **Framework preset**: `Vite`
   - **Build command**: `cd frontend && npm ci && npm run build`
   - **Build output directory**: `frontend/dist`
   - **Root directory**: leave blank (project root)
   - **Node version env var**: `NODE_VERSION=20`
4. **Environment variables** (Settings → Environment variables, scope
   to "Production" or both):
   ```
   VITE_API_BASE              https://api.your-domain.com/api/v1
   ```
5. Trigger first deploy. Subsequent commits to `main` auto-deploy.

### Option B — `wrangler` CLI (manual / CI)

```bash
npm i -g wrangler
cd frontend
npm ci && npm run build

# First time only — picks the project / creates it
wrangler pages deploy dist --project-name interview-copilot

# Subsequent deploys
wrangler pages deploy dist --project-name interview-copilot --branch main
```

`wrangler.toml` is intentionally NOT committed because Pages-only
projects don't need it; the dashboard / CLI flags are enough.

## Custom domain

In the project's **Custom domains** tab, add `app.your-domain.com`.
Cloudflare auto-provisions a TLS cert via the Universal SSL setup.

If your apex `your-domain.com` is on Cloudflare DNS, also add a
`CNAME @ app.your-domain.com.cdn.cloudflare.net` flattening for naked
domain support.

## CORS — backend must allow the Pages origin

Add the Pages preview + production hostnames to backend `.env`:

```ini
CORS_ORIGINS=https://app.your-domain.com,https://interview-copilot.pages.dev
```

(If you want PR-preview URLs to also work, add a
`https://*.interview-copilot.pages.dev` style wildcard. FastAPI's
`CORSMiddleware` doesn't support wildcards in `allow_origins` — switch
to `allow_origin_regex=r"https://.*\.interview-copilot\.pages\.dev"` in
`backend/app/main.py` if you need this.)

## Cache & header behaviour

The repo already ships:

- `frontend/public/_headers` — long-cache hashed assets, no-cache the
  HTML shell, security headers (X-Frame-Options / nosniff /
  Referrer-Policy / Permissions-Policy)
- `frontend/public/_redirects` — `/* → /index.html 200` SPA fallback

These get copied into `dist/` by Vite at build time and Pages
auto-detects them. You don't need to configure cache rules in the
dashboard.

## Cost & limits (free plan)

- 500 builds / month
- Unlimited bandwidth + requests
- 100 custom domains per project
- 25 MiB max file size (we're well under — largest asset is the Inter
  variable font at ~1.2 MB)

For most small/mid teams the free plan is enough indefinitely. The
$20/mo Pro tier mainly buys you more concurrent builds and image
transformations.

## Observability tip

If you want to see traffic / cache-hit ratio per asset path: dashboard
→ project → **Analytics**. The default dashboard already shows P50/P95
latency from the edge by region — this is how you'd verify the
"200 ms → 30 ms in China" claim before/after.
