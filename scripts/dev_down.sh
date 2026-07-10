#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for service in api web; do
  pid_file="work/${service}.pid"
  if [[ -f "$pid_file" ]]; then
    kill "$(cat "$pid_file")" 2>/dev/null || true
    rm -f "$pid_file"
  fi
done

if ! command -v docker-credential-osxkeychain >/dev/null 2>&1; then
  chmod +x scripts/docker-helpers/docker-credential-osxkeychain
  export PATH="$ROOT/scripts/docker-helpers:$PATH"
fi
docker compose -f deploy/docker-compose/compose.yaml down

