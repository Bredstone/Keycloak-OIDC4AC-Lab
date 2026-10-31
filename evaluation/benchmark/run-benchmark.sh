#!/usr/bin/env bash
# Runs the timing benchmark with fresh containers in every run.
# Usage: evaluation/benchmark/run-benchmark.sh [output-dir]
# Each run rotates the pinned CPU pairs among the three Keycloak instances and
# the order in which they start. OIDC4AC_BENCHMARK_RUNS (default 10),
# OIDC4AC_BENCHMARK_WARMUPS, and OIDC4AC_BENCHMARK_SAMPLES shorten a trial run.
set -euo pipefail
BENCH=$(cd "$(dirname "$0")" && pwd)
LAB=$(cd "$BENCH/../.." && pwd)
OUT=$(mkdir -p "${1:-$LAB/.runtime/evaluation/timing}" && cd "${1:-$LAB/.runtime/evaluation/timing}" && pwd)
RUNS=${OIDC4AC_BENCHMARK_RUNS:-10}
FIXTURES=$OUT/fixtures
mkdir -p "$FIXTURES"

# Official Keycloak 26.7.0 distribution, verified against its published SHA-1.
OFFICIAL_TARBALL=$LAB/.build/keycloak-26.7.0.tar.gz
OFFICIAL_SHA1=d0525120aa3073486bc54a66760cab0cbeedf0dd
if [[ ! -f "$OFFICIAL_TARBALL" ]]; then
  mkdir -p "$LAB/.build"
  curl -fsSL -o "$OFFICIAL_TARBALL" https://github.com/keycloak/keycloak/releases/download/26.7.0/keycloak-26.7.0.tar.gz
fi
echo "$OFFICIAL_SHA1  $OFFICIAL_TARBALL" | sha1sum -c --quiet

python3 "$BENCH/make-fixtures.py" "$LAB/config/realm-import.json" "$FIXTURES"
OFFICIAL_CONTEXT=$(mktemp -d)
cp "$OFFICIAL_TARBALL" "$OFFICIAL_CONTEXT/keycloak-26.7.0.tar.gz"
docker build -q -f "$BENCH/Dockerfile.official" -t oidc4ac-benchmark-keycloak-official:26.7.0 "$OFFICIAL_CONTEXT"
rm -rf "$OFFICIAL_CONTEXT"

cd "$LAB"
export BENCH_FIXTURES=$FIXTURES CLIENT_CPUS=4-7 KC_OFFICIAL_CPUS=0-1 KC_DISABLED_CPUS=2-3 KC_ENABLED_CPUS=8-9
dc() { docker compose -p oidc4ac-benchmark -f docker-compose.yml -f "$BENCH/compose.benchmark.yml" \
  --profile browser-e2e --profile disabled-e2e --profile benchmark --profile e2e "$@"; }
wait_url() { for _ in $(seq 1 180); do curl -fsS -o /dev/null "$1" 2>/dev/null && return 0; sleep 1; done; echo "not ready: $1"; return 1; }

CPU=/sys/devices/system/cpu/cpu0/cpufreq
export OIDC4AC_BENCHMARK_CPU_FREQUENCY="driver=$(cat $CPU/scaling_driver) governor=$(cat $CPU/scaling_governor) epp=$(cat $CPU/energy_performance_preference 2>/dev/null || echo n/a) profile=$(cat /sys/firmware/acpi/platform_profile 2>/dev/null || echo n/a)"
PAIRS=(0-1 2-3 8-9)
INSTANCES=(keycloak-official keycloak-disabled keycloak)
dc build -q
for RUN in $(seq 1 "$RUNS"); do
  export KC_OFFICIAL_CPUS=${PAIRS[$(( (RUN - 1) % 3 ))]}
  export KC_DISABLED_CPUS=${PAIRS[$(( RUN % 3 ))]}
  export KC_ENABLED_CPUS=${PAIRS[$(( (RUN + 1) % 3 ))]}
  dc down -v >/dev/null 2>&1 || true
  dc up -d smtp4dev
  for i in 0 1 2; do dc up -d --no-deps "${INSTANCES[$(( (i + RUN - 1) % 3 ))]}"; done
  wait_url http://localhost:8188/realms/oidc4ac/.well-known/openid-configuration
  wait_url http://localhost:8187/realms/oidc4ac/.well-known/openid-configuration
  wait_url http://localhost:8186/realms/oidc4ac/.well-known/openid-configuration
  wait_url http://localhost:8186/realms/oidc4ac-off/.well-known/openid-configuration
  dc up -d --no-deps browser-test-client client-realm-disabled client-feature-disabled client-official
  for port in 5003 5005 5006 5007; do wait_url "http://localhost:$port/healthz"; done
  # Factor collection for the full request (WebAuthn and email) happens once,
  # in the browser, before warm-up; the runner reuses that SSO session.
  SEED="seed-run-$(printf %02d "$RUN").json"
  dc run --rm --no-deps -v "$BENCH:/bench:ro" -v "$OUT:/out" -e PYTHONPATH=/browser-e2e \
    -e OIDC4AC_SEED_OUTPUT="/out/$SEED" --entrypoint python browser-e2e /bench/seed-session.py
  dc run --rm --no-deps -v "$BENCH:/bench:ro" -v "$OUT:/out" -e PYTHONPATH=/e2e \
    -e OIDC4AC_BENCHMARK_SEED="/out/$SEED" -e OIDC4AC_BENCHMARK_RUN="$RUN" -e OIDC4AC_BENCHMARK_OUTPUT="/out/run-$(printf %02d "$RUN").json" \
    -e KC_OFFICIAL_CPUS -e KC_DISABLED_CPUS -e KC_ENABLED_CPUS -e CLIENT_CPUS \
    -e OIDC4AC_BENCHMARK_WARMUPS -e OIDC4AC_BENCHMARK_SAMPLES -e OIDC4AC_BENCHMARK_CPU_FREQUENCY \
    --entrypoint python e2e /bench/timing-benchmark.py
  rm -f "$OUT/$SEED"
done
dc down -v >/dev/null 2>&1
