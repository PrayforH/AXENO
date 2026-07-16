#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-harness}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin}"
export HARNESS_NEW_API_BASE_URL="${HARNESS_NEW_API_BASE_URL:-http://127.0.0.1:1}"
export HARNESS_NEW_API_KEY="${HARNESS_NEW_API_KEY:-local-placeholder}"
export HARNESS_NEW_API_MODEL="${HARNESS_NEW_API_MODEL:-local-placeholder}"

stop_matching() {
  local pattern="$1"
  pkill -f "$pattern" 2>/dev/null || true
}

stop_listener() {
  local port="$1"
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done < <(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
}

for service in api web; do
  pid_file="work/${service}.pid"
  if [[ -f "$pid_file" ]]; then
    kill "$(cat "$pid_file")" 2>/dev/null || true
    rm -f "$pid_file"
  fi
done

stop_matching "$ROOT/.venv/bin/uvicorn harness.api.app:app"
stop_matching "$ROOT/web/harness-console/node_modules/.bin/next dev"
stop_listener 8000
stop_listener 3000

if ! command -v docker-credential-osxkeychain >/dev/null 2>&1; then
  chmod +x scripts/docker-helpers/docker-credential-osxkeychain
  export PATH="$ROOT/scripts/docker-helpers:$PATH"
fi
docker compose -f deploy/docker-compose/compose.yaml down
