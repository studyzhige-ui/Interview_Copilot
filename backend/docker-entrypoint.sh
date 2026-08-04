#!/bin/sh
# Container entrypoint for the API and worker images.
#
# Two jobs:
#   1. Make sure /app/data exists and the non-root ``app`` user owns it.
#      docker-compose users may bind-mount ./data → /app/data. We create the
#      writable runtime directories, but never recursively chown a model cache:
#      it can contain tens of gigabytes and is commonly shared by workers.
#   2. Drop privileges to the ``app`` user via gosu, then exec whatever
#      CMD the image was launched with (uvicorn, gunicorn, celery, …).
#
# We intentionally chown only the data dir, not /app itself — application
# code is owned by ``app`` at image-build time (see Dockerfile COPY
# --chown), and re-chowning a few-thousand-file source tree on every
# container start would slow boot for no benefit.

set -e

DATA_DIR="${APP_DATA_DIR:-/app/data}"

# Create + take ownership only if we're booted as root. When the operator
# already runs ``docker run --user 1001:1001`` we have no choice but to
# trust that the bind-mount permissions are correct, so skip the chown.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    mkdir -p "$DATA_DIR/cache" "$DATA_DIR/logs" "$DATA_DIR/runtime" \
        "$DATA_DIR/storage" "$DATA_DIR/agent-results" "$DATA_DIR/tmp"
    chown app:app "$DATA_DIR" "$DATA_DIR/cache" "$DATA_DIR/logs" "$DATA_DIR/runtime" \
        "$DATA_DIR/storage" "$DATA_DIR/agent-results" "$DATA_DIR/tmp" 2>/dev/null || true
    exec gosu app "$@"
fi

# Already non-root — just exec.
exec "$@"
