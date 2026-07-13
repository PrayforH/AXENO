#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p work
HARNESS_RUNTIME="${HARNESS_RUNTIME:-fake}"

if ! command -v docker-credential-osxkeychain >/dev/null 2>&1; then
  chmod +x scripts/docker-helpers/docker-credential-osxkeychain
  export PATH="$ROOT/scripts/docker-helpers:$PATH"
fi

docker compose -f deploy/docker-compose/compose.yaml up -d
uv run python scripts/wait_for_local_services.py
uv run alembic upgrade head

if [[ ! -f work/api.pid ]] || ! kill -0 "$(cat work/api.pid)" 2>/dev/null; then
  HARNESS_RUNTIME="$HARNESS_RUNTIME" \
    HARNESS_LOCAL_AUTO_EXECUTE=true HARNESS_OTEL_ENABLED=false \
    nohup uv run uvicorn harness.api.app:app --host 127.0.0.1 --port 8000 \
    >work/api.log 2>&1 &
  echo $! > work/api.pid
fi

api_ready=false
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null 2>&1; then
    api_ready=true
    break
  fi
  sleep 1
done
if [[ "$api_ready" != true ]]; then
  echo "Harness API did not become ready" >&2
  tail -80 work/api.log >&2 || true
  exit 1
fi
uv run python scripts/bootstrap_local_agent.py

if [[ ! -f work/web.pid ]] || ! kill -0 "$(cat work/web.pid)" 2>/dev/null; then
  (
    cd web/harness-console
    NEXT_PUBLIC_HARNESS_RUNTIME="$HARNESS_RUNTIME" \
      HARNESS_API_URL=http://127.0.0.1:8000 \
      HARNESS_AGENT_NAME=echo-agent \
      HARNESS_AGENT_VERSION=0.2.0 \
      HARNESS_TENANT_ID=local \
      HARNESS_USER_ID=developer \
      nohup npm run dev -- --hostname 127.0.0.1 >"$ROOT/work/web.log" 2>&1 &
    echo $! > "$ROOT/work/web.pid"
  )
fi

ready=false
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:3000 >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  echo "API or Web console did not become ready" >&2
  tail -80 work/api.log >&2 || true
  tail -80 work/web.log >&2 || true
  exit 1
fi

echo "Harness API: http://127.0.0.1:8000/docs"
echo "Harness Console: http://127.0.0.1:3000"
echo "Local Agent: echo-agent@0.2.0"
echo "Runtime: $HARNESS_RUNTIME"
echo "Langfuse/OTLP: disabled"
