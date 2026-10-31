#!/usr/bin/env bash
# Measures OIDC4AC message sizes in the laboratory.
# Usage: evaluation/benchmark/run-message-sizes.sh [output-dir]
set -euo pipefail
BENCH=$(cd "$(dirname "$0")" && pwd)
LAB=$(cd "$BENCH/../.." && pwd)
OUT=$(mkdir -p "${1:-$LAB/.runtime/evaluation/sizes}" && cd "${1:-$LAB/.runtime/evaluation/sizes}" && pwd)
cd "$LAB"
dc() { docker compose -p oidc4ac-sizes --profile browser-e2e "$@"; }
wait_url() { for _ in $(seq 1 180); do curl -fsS -o /dev/null "$1" 2>/dev/null && return 0; sleep 1; done; echo "not ready: $1"; return 1; }

dc down -v >/dev/null 2>&1 || true
dc up --build -d smtp4dev keycloak browser-test-client
wait_url http://localhost:8186/realms/oidc4ac/.well-known/openid-configuration
wait_url http://localhost:5003/healthz
status=0
dc run --rm --no-deps -v "$BENCH:/bench:ro" -v "$OUT:/out" -e PYTHONPATH=/browser-e2e \
  -e OIDC4AC_SIZES_OUTPUT=/out/message-sizes.json --entrypoint python browser-e2e /bench/message-sizes.py || status=$?
dc down -v >/dev/null 2>&1
exit $status
