#!/usr/bin/env bash
# Runs the compatibility matrix with the enabled (8186/5003) and disabled (8187/5001) laboratory services.
# Usage: evaluation/compatibility/run-compatibility-matrix.sh
set -uo pipefail
MATRIX=$(cd "$(dirname "$0")" && pwd)
LAB=$(cd "$MATRIX/../.." && pwd)
cd "$LAB"
dc() { docker compose -p oidc4ac-compatibility "$@"; }
wait_url() { for _ in $(seq 1 180); do curl -fsS -o /dev/null "$1" && return 0; sleep 1; done; return 1; }
dc --profile browser-e2e --profile disabled-e2e up --build -d smtp4dev keycloak browser-test-client keycloak-disabled
wait_url http://localhost:8186/realms/oidc4ac/.well-known/openid-configuration || { echo "enabled Keycloak not ready"; exit 1; }
wait_url http://localhost:8187/realms/oidc4ac/.well-known/openid-configuration || { echo "disabled Keycloak not ready"; exit 1; }
# The disabled server has no planner, so the realm uses Keycloak's built-in browser flow (as tests/feature-disabled.py does).
TOKEN=$(curl -fsS -d grant_type=password -d client_id=admin-cli -d username=admin -d password=admin \
  http://localhost:8187/realms/master/protocol/openid-connect/token | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8187/admin/realms/oidc4ac \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); r["browserFlow"]="browser"; print(json.dumps(r))' \
  | curl -fsS -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data-binary @- http://localhost:8187/admin/realms/oidc4ac
dc --profile browser-e2e run -d --no-deps --name oidc4ac-disabled-client \
  -e OIDC_ISSUER=http://localhost:8187/realms/oidc4ac -e PORT=5001 browser-test-client >/dev/null
wait_url http://client.localhost:5001/healthz || wait_url http://localhost:5001/healthz || { echo "disabled client not ready"; exit 1; }
dc --profile e2e run --build --rm --no-deps -v "$MATRIX:/matrix:ro" -e PYTHONPATH=/e2e --entrypoint python e2e /matrix/oidc4ac-compatibility-matrix.py
status=$?
docker rm -f oidc4ac-disabled-client >/dev/null 2>&1
dc --profile browser-e2e --profile disabled-e2e down >/dev/null 2>&1
echo "exit $status"
