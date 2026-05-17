#!/usr/bin/env bash
# Interview Copilot — one-time bootstrap (Linux / macOS).
#
# Brings a fresh clone to a "ready to develop" state. Run once after
# cloning. For everyday startup, use scripts/start.sh.
#
# What this script does:
#   1. Verify prerequisites (docker, npm, python in supported range)
#   2. Verify you're in an activated venv / conda env
#   3. pip install -r requirements.txt
#   4. Create .env from a template if missing (interactive)
#   5. Generate SECRET_KEY if blank
#   6. docker compose up -d  +  wait for postgres
#   7. alembic upgrade head
#   8. cd frontend && npm install
#
# What this script does NOT do:
#   - Create or activate your Python environment. Do that yourself first.
#   - Download Whisper / Pyannote model weights. Run
#     `python scripts/init_models.py` separately if you chose full mode.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { printf "${CYAN}==> %s${NC}\n" "$*"; }
ok()   { printf "    ${GREEN}%s${NC}\n" "$*"; }
warn() { printf "    ${YELLOW}%s${NC}\n" "$*"; }
fail() { printf "    ${RED}%s${NC}\n" "$*"; exit 1; }

# -----------------------------------------------------------------------------
# 1. Prerequisites
# -----------------------------------------------------------------------------
step "Checking prerequisites"

for cmd in docker npm python; do
    command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is not on PATH. Install it (or activate your env) and retry."
done

# Python version: require 3.10 / 3.11 / 3.12. 3.13 has no whisperx/pyannote
# wheels yet; <3.10 is unsupported by torch 2.x and pydantic v2.
PY_VER="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PY_VER" in
    3.10|3.11|3.12) ;;
    *) fail "Python $PY_VER is not supported. Use 3.10, 3.11, or 3.12. (3.13 lacks ML wheels.)" ;;
esac
ok "python $PY_VER  ($(python -c 'import sys; print(sys.executable)'))"

# Verify the user is in an isolated env. Installing 3 GB of ML deps into
# system Python is almost always a mistake.
if [ -z "${VIRTUAL_ENV:-}" ] && \
   { [ -z "${CONDA_PREFIX:-}" ] || [ "${CONDA_PREFIX:-}" = "${CONDA_PREFIX_1:-}" ]; }; then
    warn "You appear to be using the system / conda-base Python."
    warn "Installing ~3 GB of dependencies here will pollute it."
    warn "Recommended:"
    warn "    python -m venv .venv && source .venv/bin/activate"
    warn "  or"
    warn "    conda create -n interview-copilot python=3.12 -y && conda activate interview-copilot"
    fail "Activate an isolated env first, then re-run this script."
fi
ok "isolated environment detected"

# -----------------------------------------------------------------------------
# 2. Python dependencies
# -----------------------------------------------------------------------------
step "Installing Python dependencies (this can take 5-15 min on first run)"
( cd "$PROJECT_ROOT" && python -m pip install --upgrade pip && python -m pip install -r requirements.txt ) \
    || fail "pip install failed."
ok "requirements.txt installed"

# -----------------------------------------------------------------------------
# 3. .env scaffolding
# -----------------------------------------------------------------------------
step "Configuring .env"
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    ok ".env already exists, leaving it alone"
else
    printf "    Choose a starting template:\n"
    printf "      [1] API-light    — all cloud APIs, no GPU, no model downloads\n"
    printf "      [2] Local-models — embeddings/reranker/ASR run locally\n"
    read -rp "    Enter 1 or 2: " choice
    case "$choice" in
        2) TEMPLATE=".env.example" ;;
        *) TEMPLATE=".env.example.lite" ;;
    esac
    cp "$PROJECT_ROOT/$TEMPLATE" "$ENV_FILE"
    ok "Copied $TEMPLATE -> .env"
    warn "Remember to fill in your API keys before the first run."
fi

[ -f "$PROJECT_ROOT/.env.docker" ] || {
    cp "$PROJECT_ROOT/.env.docker.example" "$PROJECT_ROOT/.env.docker"
    ok "Copied .env.docker.example -> .env.docker"
}

# Auto-generate SECRET_KEY if blank.
if grep -qE '^SECRET_KEY=[[:space:]]*$' "$ENV_FILE"; then
    NEW_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    # Use a temp file for portability (BSD vs GNU sed).
    awk -v k="$NEW_KEY" '/^SECRET_KEY=[[:space:]]*$/{print "SECRET_KEY=" k; next} {print}' \
        "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    ok "Generated a fresh SECRET_KEY into .env"
fi

# -----------------------------------------------------------------------------
# 4. Infrastructure
# -----------------------------------------------------------------------------
step "Starting Docker infrastructure (postgres, redis, minio, milvus)"
( cd "$PROJECT_ROOT" && docker compose up -d ) || fail "docker compose up failed."

step "Waiting for postgres to accept connections"
for _ in $(seq 1 30); do
    if docker exec interview_copilot_db pg_isready -U postgres >/dev/null 2>&1; then
        ok "postgres ready"
        break
    fi
    sleep 1
done

# -----------------------------------------------------------------------------
# 5. Database migrations
# -----------------------------------------------------------------------------
step "Running database migrations"
( cd "$PROJECT_ROOT" && python -c "from alembic.config import CommandLine; CommandLine().main(['upgrade','head'])" ) \
    || fail "alembic upgrade head failed."
ok "schema is up to date"

# -----------------------------------------------------------------------------
# 6. Frontend
# -----------------------------------------------------------------------------
step "Installing frontend dependencies"
( cd "$FRONTEND_DIR" && npm install ) || fail "npm install failed."
ok "frontend deps installed"

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo
printf "${GREEN}==================================================================${NC}\n"
printf "${GREEN}  Setup complete.${NC}\n"
printf "${GREEN}==================================================================${NC}\n"
echo
echo "  Next steps:"
echo "    1. Open .env and fill in any provider API keys you want to use"
echo "       (DEEPSEEK_API_KEY at minimum, for the LLM)."
echo "    2. (full mode only) python scripts/init_models.py"
echo "       — downloads Whisper / Pyannote weights for local inference."
echo "    3. ./scripts/start.sh"
echo "       — every-day startup (uvicorn + celery + vite, single shell)."
echo "       (Run with ./ prefix; sourcing or invoking via a child shell"
echo "        can drop the conda/venv activation.)"
echo
