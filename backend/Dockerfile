# ──────────────────────────────────────────────────────────────────────────
# Interview Copilot — Production Backend Image (multi-stage)
# ──────────────────────────────────────────────────────────────────────────

# Stage 1: Build dependencies into a virtual environment
FROM python:3.13-slim AS builder

WORKDIR /build

# System dependencies for building native wheels (psycopg2, bcrypt, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /opt/venv/bin/pip install --no-cache-dir gunicorn

# Stage 2: Lean runtime image
FROM python:3.13-slim AS runtime

# libpq is needed at runtime for psycopg2; curl is the healthcheck client;
# gosu (~1MB) lets entrypoint drop privileges *after* fixing /app/data
# ownership — useful when a bind-mounted volume comes in owned by host UID.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl gosu && \
    rm -rf /var/lib/apt/lists/*

# ── Non-root runtime user ────────────────────────────────────────────────
# Fixed UID/GID 1001 so volume permissions are reproducible across hosts
# and CI. ``--no-create-home`` keeps the image lean; ``/sbin/nologin`` is
# defensive in depth (the user has no interactive shell anyway).
RUN groupadd --system --gid 1001 app && \
    useradd --system --uid 1001 --gid app \
            --no-create-home --shell /sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Tell pydantic-settings / app code that runtime state lives at
    # /app/data — entrypoint chowns this dir to the app user before
    # exec'ing the server.
    APP_DATA_DIR=/app/data

WORKDIR /app

# Copy source. --chown gives the app user ownership inside the image so
# read-only operations (importing modules, reading alembic migrations)
# don't need any further filesystem mucking.
COPY --chown=app:app backend/ ./
COPY --chown=app:app alembic.ini /app/alembic.ini
COPY --chown=app:app alembic/ /app/alembic/

# Entrypoint creates /app/data if missing, chowns it (handles the case
# where docker-compose bind-mounts a host dir owned by root or some other
# UID), then drops to the app user via gosu before exec'ing the CMD.
COPY --chown=root:root backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/ping || exit 1

# Entry point bootstraps data dir + drops privileges. CMD is whatever
# server (uvicorn / gunicorn / celery) the compose service wants.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default: run API server with gunicorn + uvicorn workers
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "--access-logfile", "-"]
