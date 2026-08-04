#!/usr/bin/env bash
# Interview Copilot — daily development startup (Linux / macOS).
#
# Idempotent. Brings everything up in the current terminal:
#   1. docker compose up -d --wait    (no-op if already running)
#   2. alembic upgrade head           (no-op if already at head)
#   3. uvicorn (backend, --reload)    -> background
#   4. celery worker + beat           -> background
#   5. vite dev server (frontend)     -> background
#
# The terminal shows a concise, color-coded status view; complete job streams
# are written to data/logs. Ctrl+C stops everything cleanly.
#
# Run scripts/setup.sh once before the first time you call this.
#
# Flags:
#   --skip-backend     Only start the frontend
#   --skip-frontend    Only start the backend (uvicorn + celery)
#   --api-port N       Backend port (default 8080)
#   --frontend-port N  Frontend port (default 5173; auto-bumps if taken)
#   --verbose-logs      Stream full logs instead of the concise status view

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
mkdir -p "$PROJECT_ROOT/data/tmp" "$PROJECT_ROOT/data/cache/pycache"
export TMPDIR="$PROJECT_ROOT/data/tmp"
export PYTHONPYCACHEPREFIX="$PROJECT_ROOT/data/cache/pycache"

API_PORT=8080
FRONT_PORT=5173
SKIP_BACKEND=0
SKIP_FRONTEND=0
VERBOSE_LOGS=0

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-backend)    SKIP_BACKEND=1; shift ;;
        --skip-frontend)   SKIP_FRONTEND=1; shift ;;
        --api-port)        API_PORT="$2"; shift 2 ;;
        --frontend-port)   FRONT_PORT="$2"; shift 2 ;;
        --verbose-logs)    VERBOSE_LOGS=1; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

DARK_GRAY='\033[0;90m'; CYAN='\033[0;36m'; GREEN='\033[0;32m'
YELLOW='\033[1;33m'; MAGENTA='\033[0;35m'; BLUE='\033[0;34m'
RED='\033[0;31m'; NC='\033[0m'

log() {
    local tag="$1"; local color="$2"; shift 2
    printf "${DARK_GRAY}[%s]${NC} ${color}[%s]${NC} %s\n" "$(date +%H:%M:%S)" "$tag" "$*"
}

LOG_DIR="$PROJECT_ROOT/data/logs"
mkdir -p "$LOG_DIR"
if [ "$SKIP_FRONTEND" = "1" ]; then LOG_ROLE="backend"
elif [ "$SKIP_BACKEND" = "1" ];  then LOG_ROLE="frontend"
else                                   LOG_ROLE="both"
fi
LOG_FILE="$LOG_DIR/${LOG_ROLE}-$(date +%Y%m%d-%H%M%S).log"

record_command_output() {
    local tag="$1" color="$2" line
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        printf '[%s] [%s] %s\n' "$(date +%H:%M:%S)" "$tag" "$line" >> "$LOG_FILE"
        [ "$VERBOSE_LOGS" = "1" ] && log "$tag" "$color" "$line"
    done
}

stream_service_output() {
    local tag="$1" color="$2" line
    while IFS= read -r line; do
        printf '[%s] [%s] %s\n' "$(date +%H:%M:%S)" "$tag" "$line" >> "$LOG_FILE"
        if [ "$VERBOSE_LOGS" = "1" ] || printf '%s' "$line" | grep -Eqi \
            '(WARNING|ERROR|CRITICAL|Traceback|Exception|failed|startup sequence (begins|complete)|Application startup complete|VITE v.+ready|Local:[[:space:]]+http|RAG embedding ready|Reranker ready|WhisperX (加载|ready)|Pyannote diarization ready|Worker voice runtime ready|celery@.+ ready\.|model_catalog seed loaded)'; then
            log "$tag" "$color" "$line"
        fi
    done
}

# Find a free TCP port near $1 by trying to bind.
find_free_port() {
    local start="$1"
    for p in $(seq "$start" $((start + 19))); do
        if ! (echo > "/dev/tcp/127.0.0.1/$p") >/dev/null 2>&1; then
            echo "$p"; return
        fi
    done
    echo "$start"  # give up, return original
}

# -----------------------------------------------------------------------------
# 1. Sanity checks
# -----------------------------------------------------------------------------
if [ "$SKIP_BACKEND" = "0" ]; then
    command -v python >/dev/null || { log Init "$RED" "python not found. Activate your env, or run scripts/setup.sh first."; exit 1; }
    if ! python -c "import fastapi, alembic, uvicorn, celery" 2>/dev/null; then
        log Init "$RED" "Backend dependencies are missing. Run scripts/setup.sh."
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# 2. Docker infrastructure (idempotent)
# -----------------------------------------------------------------------------
if [ "$SKIP_BACKEND" = "0" ]; then
    log Docker "$MAGENTA" "starting long-running infrastructure ..."
    ( cd "$PROJECT_ROOT" && docker compose up -d --wait --wait-timeout 180 \
        db redis minio milvus-etcd milvus-minio milvus-standalone 2>&1 ) | record_command_output Docker "$DARK_GRAY"
    ( cd "$PROJECT_ROOT" && docker compose run --rm --no-deps minio-create-bucket 2>&1 ) | record_command_output Docker "$DARK_GRAY"
    log Docker "$GREEN" "infrastructure healthy"
fi

# -----------------------------------------------------------------------------
# 3. Alembic (idempotent)
# -----------------------------------------------------------------------------
if [ "$SKIP_BACKEND" = "0" ]; then
    log Alembic "$BLUE" "upgrade head ..."
    if ! ( cd "$PROJECT_ROOT" && python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])" 2>&1 ) | record_command_output Alembic "$DARK_GRAY"; then
        log Alembic "$RED" "Migration failed. Backend will refuse to start until fixed."
        log Alembic "$YELLOW" "Details: $LOG_FILE"
        exit 1
    fi
    log Alembic "$GREEN" "schema is current"
fi

# -----------------------------------------------------------------------------
# 4. Background processes
# -----------------------------------------------------------------------------
PIDS=()

if [ "$SKIP_BACKEND" = "0" ]; then
    log API "$GREEN" "uvicorn -> http://localhost:$API_PORT"
    ( cd "$BACKEND_DIR" && python -m uvicorn app.main:app --reload --port "$API_PORT" ) \
        2>&1 | stream_service_output uvicorn "$GREEN" &
    PIDS+=($!)

    log Celery "$YELLOW" "jobs worker -> default,background,pipeline,transcription; --pool=solo"
    ( cd "$BACKEND_DIR" && python -m celery -A app.task_queue.celery_app.celery_app worker --loglevel=info --pool=solo --queues=default,background,pipeline,transcription ) \
        2>&1 | stream_service_output celery "$YELLOW" &
    PIDS+=($!)

    log Turns "$CYAN" "conversation worker -> turns; --pool=threads"
    ( cd "$BACKEND_DIR" && python -m celery -A app.task_queue.celery_app.celery_app worker --loglevel=info --pool=threads --concurrency=2 --queues=turns ) \
        2>&1 | stream_service_output turns "$CYAN" &
    PIDS+=($!)

    log Beat "$MAGENTA" "scheduler"
    ( cd "$BACKEND_DIR" && python -m celery -A app.task_queue.celery_app.celery_app beat --loglevel=info --schedule "$PROJECT_ROOT/data/runtime/celerybeat-schedule" ) \
        2>&1 | stream_service_output beat "$MAGENTA" &
    PIDS+=($!)
fi

if [ "$SKIP_FRONTEND" = "0" ]; then
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log npm "$YELLOW" "node_modules missing — running npm ci (one-time)"
        ( cd "$FRONTEND_DIR" && npm ci --no-audit --no-fund )
    fi
    PORT="$(find_free_port "$FRONT_PORT")"
    [ "$PORT" != "$FRONT_PORT" ] && log Vite "$YELLOW" "Port $FRONT_PORT taken; using $PORT"
    log Vite "$CYAN" "vite -> http://localhost:$PORT"
    ( cd "$FRONTEND_DIR" && npm run dev -- --port "$PORT" ) \
        2>&1 | stream_service_output vite "$CYAN" &
    PIDS+=($!)
fi

if [ ${#PIDS[@]} -eq 0 ]; then
    log Done "$YELLOW" "Nothing to start (--skip-backend and --skip-frontend both set)."
    exit 0
fi

echo
log Starting "$GREEN" "Processes launched; readiness messages will follow."
log Starting "$GREEN" "Log file: $LOG_FILE"
[ "$VERBOSE_LOGS" = "0" ] && log Starting "$DARK_GRAY" "Console mode: concise (use --verbose-logs for full output)"
echo

cleanup() {
    echo
    log Shutdown "$RED" "Stopping ${#PIDS[@]} processes..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    log Shutdown "$RED" "Done. Full log: $LOG_FILE"
}
trap cleanup INT TERM EXIT

# Block until any child exits or user hits Ctrl+C.
wait -n "${PIDS[@]}" 2>/dev/null || true
log Shutdown "$RED" "A service exited; tearing down the rest."
