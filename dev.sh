#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KEYCLOAK_REPO=${OIDC4AC_LAB_KEYCLOAK_REPO:-$ROOT_DIR/../keycloak-OIDC4AC}
if [[ "$KEYCLOAK_REPO" != /* ]]; then
    KEYCLOAK_REPO="$ROOT_DIR/$KEYCLOAK_REPO"
fi
RUNTIME_DIR="$ROOT_DIR/.runtime"
BUILD_DIR="$ROOT_DIR/.build"
PROVIDER_DIR="$ROOT_DIR/providers/oidc4ac-test-email"
KEYCLOAK_PID_FILE="$RUNTIME_DIR/keycloak.pid"
KEYCLOAK_LOG="$RUNTIME_DIR/keycloak.log"
KEYCLOAK_ARCHIVE="$BUILD_DIR/keycloak-26.7.0.tar.gz"
ISSUER="${OIDC4AC_LAB_ISSUER:-http://keycloak.localhost:8080/realms/oidc4ac}"
CLIENT_URL="${OIDC4AC_LAB_CLIENT_URL:-http://client.localhost:${OIDC4AC_LAB_CLIENT_PORT:-5000}}"

compose() {
    docker compose -f "$ROOT_DIR/docker-compose.yml" "$@"
}

die() {
    echo "dev.sh: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

pid_is_running() {
    [[ -f "$KEYCLOAK_PID_FILE" ]] || return 1
    local pid
    pid=$(<"$KEYCLOAK_PID_FILE")
    [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

stop_host_keycloak() {
    if ! pid_is_running; then
        rm -f "$KEYCLOAK_PID_FILE"
        return 0
    fi

    local pid
    pid=$(<"$KEYCLOAK_PID_FILE")
    echo "Stopping Keycloak process $pid..."
    kill "$pid" 2>/dev/null || true
    for _ in {1..30}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "Keycloak did not stop within 30 seconds; sending TERM again." >&2
        kill -TERM "$pid" 2>/dev/null || true
    fi
    rm -f "$KEYCLOAK_PID_FILE"
}

wait_for_url() {
    local url=$1
    local timeout=${2:-120}
    local deadline=$((SECONDS + timeout))
    until curl --fail --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then
            return 1
        fi
        sleep 1
    done
}

build_keycloak() {
    [[ -x "$KEYCLOAK_REPO/mvnw" ]] || die "Keycloak checkout not found or mvnw is not executable: $KEYCLOAK_REPO"
    mkdir -p "$BUILD_DIR"
    if [[ "${OIDC4AC_LAB_SKIP_BUILD:-false}" != "true" ]]; then
        echo "Building Keycloak distribution from $KEYCLOAK_REPO..."
        (
            cd "$KEYCLOAK_REPO"
            ./mvnw -pl quarkus/dist -am -DskipTests -Dskip.pnpm=true package
        )
    fi

    local archive="$KEYCLOAK_REPO/quarkus/dist/target/keycloak-26.7.0.tar.gz"
    [[ -f "$archive" ]] || die "Keycloak distribution not found: $archive"
    cp "$archive" "$KEYCLOAK_ARCHIVE"
    echo "Prepared $KEYCLOAK_ARCHIVE"
}

build_provider() {
    [[ -x "$KEYCLOAK_REPO/mvnw" ]] || die "Keycloak checkout not found or mvnw is not executable: $KEYCLOAK_REPO"
    echo "Building the optional email provider..."
    (
        cd "$ROOT_DIR"
        "$KEYCLOAK_REPO/mvnw" -f "$PROVIDER_DIR/pom.xml" -DskipTests package
    )
    echo "Prepared $PROVIDER_DIR/target/oidc4ac-test-email-1.0.0-SNAPSHOT.jar"
}

start_host_keycloak() {
    require_command curl
    mkdir -p "$RUNTIME_DIR"
    if pid_is_running; then
        if wait_for_url "$ISSUER" 5; then
            echo "Keycloak is already running at $ISSUER"
            return 0
        fi
        stop_host_keycloak
    fi

    echo "Starting Keycloak from $KEYCLOAK_REPO..."
    nohup env \
        OIDC4AC_LAB_KEYCLOAK_REPO="$KEYCLOAK_REPO" \
        OIDC4AC_LAB_ISSUER="$ISSUER" \
        bash "$ROOT_DIR/scripts/start-keycloak.sh" \
        >"$KEYCLOAK_LOG" 2>&1 < /dev/null &
    echo $! >"$KEYCLOAK_PID_FILE"

    if ! wait_for_url "$ISSUER" 180; then
        echo "Keycloak did not become ready. Recent log output:" >&2
        tail -n 80 "$KEYCLOAK_LOG" >&2 || true
        stop_host_keycloak
        return 1
    fi
    echo "Keycloak is ready at $ISSUER"
}

start_client() {
    require_command docker
    echo "Starting the test client at $CLIENT_URL..."
    compose up --build -d test-client
    wait_for_url "$CLIENT_URL/healthz" 60 || die "test client did not become ready"
    echo "Test client is ready at $CLIENT_URL"
}

up() {
    start_host_keycloak
    start_client
    echo
    echo "OIDC4AC lab is running. Open $CLIENT_URL"
    echo "Use './dev.sh status' for status or './dev.sh down' to stop it."
}

test_http() {
    up
    compose --profile e2e run --build --rm e2e
}

test_browser() {
    build_keycloak
    compose --profile browser-e2e run --build --rm browser-e2e
}

test_disabled() {
    build_keycloak
    compose --profile disabled-e2e up --build -d keycloak-disabled
    local result=0
    if ! wait_for_url "http://localhost:8187/realms/master" 120; then
        echo "dev.sh: disabled Keycloak did not become ready" >&2
        result=1
    elif OIDC4AC_DISABLED_ISSUER="http://localhost:8187/realms/oidc4ac" \
        python3 "$ROOT_DIR/tests/feature-disabled.py"; then
        :
    else
        result=$?
    fi
    compose stop keycloak-disabled >/dev/null 2>&1 || true
    compose rm -f keycloak-disabled >/dev/null 2>&1 || true
    return "$result"
}

test_all() {
    test_http
    test_disabled
    test_browser
}

verify() {
    up
    OIDC4AC_LAB_ISSUER="$ISSUER" OIDC4AC_LAB_CLIENT_URL="$CLIENT_URL" \
        bash "$ROOT_DIR/scripts/verify.sh"
}

lint() {
    bash "$ROOT_DIR/scripts/lint.sh"
}

status() {
    echo "Lab root:       $ROOT_DIR"
    echo "Keycloak source: $KEYCLOAK_REPO"
    if pid_is_running; then
        echo "Keycloak host:   running (PID $(<"$KEYCLOAK_PID_FILE"))"
    else
        echo "Keycloak host:   stopped"
    fi
    compose ps
}

logs() {
    if [[ -f "$KEYCLOAK_LOG" ]]; then
        echo "--- Keycloak log: $KEYCLOAK_LOG ---"
        tail -n 80 "$KEYCLOAK_LOG"
    fi
    echo "--- Compose services ---"
    compose logs --tail=80 test-client || true
}

down() {
    compose down --remove-orphans
    stop_host_keycloak
}

clean() {
    down
    rm -rf -- "$RUNTIME_DIR" "$BUILD_DIR"
    echo "Removed generated lab runtime and build state."
}

help() {
    cat <<'EOF'
Usage: ./dev.sh [command]

Without a command, starts the lab (`up`).

Lifecycle:
  up               Build/start Keycloak and the Flask test client
  down             Stop Keycloak and Compose services
  status           Show source, process, and Compose status
  logs             Show recent Keycloak and test-client logs
  clean            Stop services and remove generated .runtime/.build state

Build and checks:
  build            Build Keycloak and prepare .build/keycloak-26.7.0.tar.gz
  provider-build   Compile the optional email provider into its ignored target/ directory
  lint             Run Python, shell, XML, and provider Spotless checks
  verify           Start the lab and run discovery/readiness checks

Tests:
  test-http        Run the 36 HTTP end-to-end scenarios
  test-browser     Run the virtual-CTAP2 browser scenarios
  test-disabled    Run the feature-disabled regression
  test             Run all lab suites

Other:
  compose ...       Pass arguments through to Docker Compose
  help              Show this help

Set OIDC4AC_LAB_KEYCLOAK_REPO when the Keycloak checkout is not the default
sibling directory ../keycloak-OIDC4AC.
EOF
}

command=${1:-up}
case "$command" in
    up) up ;;
    down) down ;;
    status) status ;;
    logs) logs ;;
    clean) clean ;;
    build) build_keycloak ;;
    provider-build) build_provider ;;
    lint) lint ;;
    verify) verify ;;
    test-http) test_http ;;
    test-browser) test_browser ;;
    test-disabled) test_disabled ;;
    test) test_all ;;
    compose)
        shift
        compose "$@"
        ;;
    help|-h|--help) help ;;
    *)
        echo "Unknown command: $command" >&2
        help >&2
        exit 2
        ;;
esac
