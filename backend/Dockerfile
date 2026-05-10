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

# libpq is needed at runtime for psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy backend source code
COPY backend/ ./

# Copy alembic config and migrations (needed for startup migration check)
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/ping || exit 1

# Default: run API server with gunicorn + uvicorn workers
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "--access-logfile", "-"]
