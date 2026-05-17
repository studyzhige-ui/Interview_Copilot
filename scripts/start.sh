#!/usr/bin/env bash
# Interview Copilot — daily development startup (Linux / macOS).
#
# Idempotent. Brings everything up in the current terminal:
#   1. docker compose up -d           (no-op if already running)
#   2. alembic upgrade head           (no-op if already at head)
#   3. uvicorn (backend, --reload)    -> background
#   4. celery worker                  -> background
#   5. vite dev server (frontend)     -> background
#
# Logs from all three streams are merged into this terminal with
# color-coded prefixes. Ctrl+C stops everything cleanly.
#
# Run scripts/setup.sh once before the first time you call this.
#
# Flags:
#   --skip-backend     Only start the frontend
#   --skip-frontend    Only start the backend (uvicorn + celery)
#   --api-port N       Backend port (default 8080)
#   --frontend-port N  Frontend port (default 5173; auto-bumps if taken)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

API_PORT=8080
FRONT_PORT=5173
SKIP_BACKEND=0
SKIP_FRONTEND=0

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-backend)    SKIP_BACKEND=1; shift ;;
        --skip-frontend)   SKIP_FRONTEND=1; shift ;;
        --api-port)        API_PORT="$2"; shift 2 ;;
        --frontend-port)   FRONT_PORT="$2"; shift 2 ;;
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
    log Docker "$MAGENTA" "docker compose up -d ..."
    ( cd "$PROJECT_ROOT" && docker compose up -d 2>&1 ) | while IFS= read -r line; do
        log Docker "$DARK_GRAY" "$line"
    done

    log Docker "$MAGENTA" "Waiting for postgres..."
    for _ in $(seq 1 30); do
        if docker exec interview_copilot_db pg_isready -U postgres >/dev/null 2>&1; then
            log Docker "$GREEN" "postgres ready"
            break
        fi
        sleep 1
    done
fi

# -----------------------------------------------------------------------------
# 3. Alembic (idempotent)
# -----------------------------------------------------------------------------
if [ "$SKIP_BACKEND" = "0" ]; then
    log Alembic "$BLUE" "upgrade head ..."
    if ! ( cd "$PROJECT_ROOT" && python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])" ); then
        log Alembic "$RED" "Migration failed. Backend will refuse to start until fixed."
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# 4. Background processes
# -----------------------------------------------------------------------------
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
# Name the log file after which mode is running — two parallel tabs (backend
# + frontend) get clearly-distinct files instead of a shared "dev-*.log".
if [ "$SKIP_FRONTEND" = "1" ]; then LOG_ROLE="backend"
elif [ "$SKIP_BACKEND" = "1" ];  then LOG_ROLE="frontend"
else                                   LOG_ROLE="both"
fi
LOG_FILE="$LOG_DIR/${LOG_ROLE}-$(date +%Y%m%d-%H%M%S).log"

PIDS=()

if [ "$SKIP_BACKEND" = "0" ]; then
    log API "$GREEN" "uvicorn -> http://localhost:$API_PORT"
    ( cd "$BACKEND_DIR" && python -m uvicorn app.main:app --reload --port "$API_PORT" ) \
        2>&1 | sed -u "s/^/[uvicorn] /" | tee -a "$LOG_FILE" &
    PIDS+=($!)

    log Celery "$YELLOW" "worker -> --pool=solo"
    ( cd "$BACKEND_DIR" && python -m celery -A app.worker.celery_app.celery_app worker --loglevel=info --pool=solo ) \
        2>&1 | sed -u "s/^/[celery]  /" | tee -a "$LOG_FILE" &
    PIDS+=($!)
fi

if [ "$SKIP_FRONTEND" = "0" ]; then
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log npm "$YELLOW" "node_modules missing — running npm install (one-time)"
        ( cd "$FRONTEND_DIR" && npm install )
    fi
    PORT="$(find_free_port "$FRONT_PORT")"
    [ "$PORT" != "$FRONT_PORT" ] && log Vite "$YELLOW" "Port $FRONT_PORT taken; using $PORT"
    log Vite "$CYAN" "vite -> http://localhost:$PORT"
    ( cd "$FRONTEND_DIR" && npm run dev -- --port "$PORT" ) \
        2>&1 | sed -u "s/^/[vite]    /" | tee -a "$LOG_FILE" &
    PIDS+=($!)
fi

if [ ${#PIDS[@]} -eq 0 ]; then
    log Done "$YELLOW" "Nothing to start (--skip-backend and --skip-frontend both set)."
    exit 0
fi

echo
log Ready "$GREEN" "====== Services started — Ctrl+C to stop all ======"
log Ready "$GREEN" "Log file: $LOG_FILE"
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
