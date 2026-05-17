# Two-stage build: compile the Vite SPA in node, serve the static dist/
# from a slim nginx image. The runtime image carries no Node — only the
# compiled assets + the matching nginx config.
#
# Build args:
#   VITE_API_BASE — baked into the bundle at build time. Default is
#                   "/api/v1" which works when both SPA and API are served
#                   behind the same reverse proxy. For split deployments
#                   pass an absolute URL like "https://api.example.com/api/v1".

# ─── Stage 1: build ──────────────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /build

# Install deps first so Docker layer cache stays warm across source changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy source and build.
COPY frontend/ ./

ARG VITE_API_BASE=/api/v1
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# ─── Stage 2: serve ──────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Drop the default config so our SPA-friendly one wins.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/conf.d/frontend.conf /etc/nginx/conf.d/frontend.conf

# Compiled assets from the build stage.
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
