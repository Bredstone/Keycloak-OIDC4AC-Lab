#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KEYCLOAK_REPO="$ROOT_DIR/.runtime/keycloak-source"
source "$ROOT_DIR/scripts/keycloak-repo.sh"
RUNTIME_DIR="$ROOT_DIR/.runtime"
BUILD_DIR="$ROOT_DIR/.build"
PROVIDER_DIR="$ROOT_DIR/providers/oidc4ac-test-email"
KEYCLOAK_PID_FILE="$RUNTIME_DIR/keycloak.pid"
KEYCLOAK_LOG="$RUNTIME_DIR/keycloak.log"
KEYCLOAK_LOG_TAIL_PID=""
KEYCLOAK_ARCHIVE="$BUILD_DIR/keycloak-26.7.0.tar.gz"
ISSUER="${OIDC4AC_LAB_ISSUER:-http://keycloak.localhost:8080/realms/oidc4ac}"
CLIENT_URL="${OIDC4AC_LAB_CLIENT_URL:-http://client.localhost:${OIDC4AC_LAB_CLIENT_PORT:-5000}}"
SMTP4DEV_WEB_URL="${OIDC4AC_LAB_SMTP_WEB_URL:-http://localhost:${OIDC4AC_LAB_SMTP_WEB_PORT:-5080}}"
KILL_ENVIRONMENT=true

compose() {
    OIDC4AC_LAB_SMTP_WEB_URL="$SMTP4DEV_WEB_URL" \
        docker compose -f "$ROOT_DIR/docker-compose.yml" "$@"
}

compose_all_profiles() {
    compose --profile '*' "$@"
}

die() {
    echo "dev.sh: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

ensure_keycloak_repo() {
    resolve_keycloak_repo "$ROOT_DIR" || die "unable to prepare the Keycloak implementation checkout"
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

keycloak_port() {
    [[ "$ISSUER" =~ ^https?://[^:/]+:([0-9]+)/ ]] || return 1
    printf '%s\n' "${BASH_REMATCH[1]}"
}

stop_conflicting_keycloak() {
    [[ "$KILL_ENVIRONMENT" == true ]] || return 0
    local port
    port=$(keycloak_port) || return 0
    command -v lsof >/dev/null 2>&1 || return 0

    local pid process
    mapfile -t listening_pids < <(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u)
    for pid in "${listening_pids[@]}"; do
        process=$(ps -p "$pid" -o args= 2>/dev/null || true)
        if [[ "$process" != *keycloak* && "$process" != *kc.sh* && "$process" != *quarkus* ]]; then
            continue
        fi

        echo "Stopping existing Keycloak process $pid on port $port..."
        kill -TERM "$pid" 2>/dev/null || true
        for _ in {1..30}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "Keycloak process $pid did not stop; sending KILL." >&2
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done
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
    ensure_keycloak_repo
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
    ensure_keycloak_repo
    [[ -x "$KEYCLOAK_REPO/mvnw" ]] || die "Keycloak checkout not found or mvnw is not executable: $KEYCLOAK_REPO"
    echo "Preparing the Keycloak SPI artifacts for the provider..."
    (
        cd "$KEYCLOAK_REPO"
        ./mvnw -N -DskipTests install
        ./mvnw -pl server-spi-private -am -DskipTests -Dskip.pnpm=true install
    )
    echo "Building the optional email provider..."
    (
        cd "$ROOT_DIR"
        "$KEYCLOAK_REPO/mvnw" -f "$PROVIDER_DIR/pom.xml" -DskipTests clean package
    )
    echo "Prepared $PROVIDER_DIR/target/oidc4ac-test-email-1.0.0-SNAPSHOT.jar"
}

start_host_keycloak() {
    ensure_keycloak_repo
    require_command curl
    mkdir -p "$RUNTIME_DIR"
    if pid_is_running; then
        if wait_for_url "$ISSUER" 5; then
            echo "Keycloak is already running at $ISSUER"
            return 0
        fi
        stop_host_keycloak
    fi

    stop_conflicting_keycloak

    if [[ "$KILL_ENVIRONMENT" != true ]] && wait_for_url "$ISSUER" 2; then
        die "Keycloak already responds at $ISSUER and --no-kill preserves it; stop that instance or choose another port."
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
    if ! pid_is_running; then
        echo "Keycloak exited before becoming ready. Recent log output:" >&2
        tail -n 80 "$KEYCLOAK_LOG" >&2 || true
        rm -f "$KEYCLOAK_PID_FILE"
        return 1
    fi
    echo "Keycloak is ready at $ISSUER"
}

start_client_detached() {
    require_command docker
    echo "Starting the test client at $CLIENT_URL for the automated checks..."
    compose up --build -d test-client
    wait_for_url "$CLIENT_URL/healthz" 60 || die "test client did not become ready"
    echo "Test client is ready at $CLIENT_URL"
}

start_smtp4dev() {
    require_command docker
    require_command curl
    echo "Starting smtp4dev at $SMTP4DEV_WEB_URL..."
    compose up -d smtp4dev
    wait_for_url "$SMTP4DEV_WEB_URL" 60 || die "smtp4dev did not become ready"
    echo "smtp4dev is ready at $SMTP4DEV_WEB_URL"
}

clean_docker_services() {
    require_command docker
    if [[ "$KILL_ENVIRONMENT" != true ]]; then
        echo "Skipping environment cleanup (--no-kill)."
        return 0
    fi

    echo "Stopping running Docker containers before the lab starts..."
    mapfile -t running_containers < <(docker ps -q)
    for container in "${running_containers[@]}"; do
        docker stop "$container" >/dev/null || true
    done

    echo "Removing this lab's Docker Compose services..."
    compose_all_profiles down --remove-orphans
}

start_lab() {
    clean_docker_services
    start_smtp4dev
    build_provider
    start_host_keycloak
    start_client_detached
}

stop_log_stream() {
    if [[ -n "$KEYCLOAK_LOG_TAIL_PID" ]]; then
        kill "$KEYCLOAK_LOG_TAIL_PID" 2>/dev/null || true
        wait "$KEYCLOAK_LOG_TAIL_PID" 2>/dev/null || true
        KEYCLOAK_LOG_TAIL_PID=""
    fi
}

stop_foreground_lab() {
    local status=$?
    trap - EXIT INT TERM
    stop_log_stream
    compose_all_profiles down --remove-orphans >/dev/null 2>&1 || true
    stop_host_keycloak
    exit "$status"
}

run() {
    trap 'exit 130' INT TERM
    trap stop_foreground_lab EXIT

    clean_docker_services
    start_smtp4dev
    build_provider
    start_host_keycloak

    # Keep both the host Keycloak log and the attached Compose log visible in
    # this terminal. Ctrl-C tears down both services through the EXIT trap.
    tail -n 20 -F "$KEYCLOAK_LOG" &
    KEYCLOAK_LOG_TAIL_PID=$!

    echo
    echo "OIDC4AC lab is running in the foreground. Open $CLIENT_URL"
    echo "Press Ctrl-C to stop the lab."
    compose up --build test-client
}

test_http() {
    start_lab
    compose --profile e2e run --build --rm e2e
}

test_browser() {
    clean_docker_services
    build_keycloak
    build_provider
    compose --profile browser-e2e run --build --rm browser-e2e
}

test_disabled() {
    clean_docker_services
    build_keycloak
    build_provider
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
    start_lab
    OIDC4AC_LAB_ISSUER="$ISSUER" OIDC4AC_LAB_CLIENT_URL="$CLIENT_URL" \
        bash "$ROOT_DIR/scripts/verify.sh"
}

lint() {
    bash "$ROOT_DIR/scripts/lint.sh"
}

status() {
    local source="$KEYCLOAK_REPO"
    echo "Lab root:       $ROOT_DIR"
    echo "Keycloak source: $source"
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
    compose logs --tail=80 smtp4dev test-client || true
}

down() {
    compose_all_profiles down --remove-orphans
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

Without a command, stops running Docker containers, cleans up this lab's Compose services, and starts the lab (`run`).

Lifecycle:
  run              Stop running containers, clean this lab's services, then start with logs attached
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
  test-http        Run the 37 HTTP end-to-end scenarios
  test-browser     Run the virtual-CTAP2 browser scenarios
  test-disabled    Run the feature-disabled regression
  test             Run all lab suites

Other:
  compose ...       Pass arguments through to Docker Compose
  --no-kill         Preserve running containers and existing Keycloak processes before startup
  help              Show this help

The wrapper shallow-clones the fork into ignored .runtime/keycloak-source.
Override the source checkout with OIDC4AC_LAB_KEYCLOAK_REPO, or override the
download with OIDC4AC_LAB_KEYCLOAK_REPO_URL and OIDC4AC_LAB_KEYCLOAK_REF.
EOF
}

command=""
remaining_args=()
while (($# > 0)); do
    case "$1" in
        --no-kill)
            KILL_ENVIRONMENT=false
            shift
            ;;
        *)
            if [[ -z "$command" ]]; then
                command="$1"
            else
                remaining_args+=("$1")
            fi
            shift
            ;;
    esac
done
command=${command:-run}
set -- "${remaining_args[@]}"
case "$command" in
    run) run ;;
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
        compose "$@"
        ;;
    help|-h|--help) help ;;
    *)
        echo "Unknown command: $command" >&2
        help >&2
        exit 2
        ;;
esac
