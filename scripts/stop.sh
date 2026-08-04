#!/usr/bin/env bash
# Interview Copilot — clean shutdown (Linux / macOS).
#
# Stops this repository's Docker Compose services. Host development processes
# belong to the terminal running start.sh and are stopped there with Ctrl+C;
# this script never scans or kills unrelated processes.
#
# Flags:
#   --volumes   Also delete docker volumes (postgres data, milvus, minio).
#               DESTRUCTIVE — wipes the database.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WIPE_VOLUMES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --volumes) WIPE_VOLUMES=1; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { printf "${CYAN}==> %s${NC}\n" "$*"; }

# -----------------------------------------------------------------------------
# Bring down docker compose
# -----------------------------------------------------------------------------
step "docker compose down"
cd "$PROJECT_ROOT"
if [ "$WIPE_VOLUMES" = "1" ]; then
    printf "    ${YELLOW}--volumes set: also removing data volumes (DESTRUCTIVE)${NC}\n"
    docker compose down -v
else
    docker compose down
fi

echo
printf "${GREEN}==================================================================${NC}\n"
if [ "$WIPE_VOLUMES" = "1" ]; then
    printf "${GREEN}  All services stopped AND data volumes wiped.${NC}\n"
    printf "${GREEN}  Next start.sh will rebuild an empty DB; alembic upgrade head${NC}\n"
    printf "${GREEN}  runs automatically as part of start.sh.${NC}\n"
else
    printf "${GREEN}  All services stopped. Data volumes preserved.${NC}\n"
fi
printf "${GREEN}==================================================================${NC}\n"
