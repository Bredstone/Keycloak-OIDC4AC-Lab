#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source "$ROOT_DIR/scripts/keycloak-repo.sh"
PROVIDER_DIR="$ROOT_DIR/providers/oidc4ac-test-email"

die() {
    echo "lint.sh: $*" >&2
    exit 1
}

command -v flake8 >/dev/null 2>&1 || die "flake8 is required; install requirements-dev.txt"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v docker >/dev/null 2>&1 || die "docker is required for Compose validation"

docker compose -f "$ROOT_DIR/docker-compose.yml" config --quiet

mapfile -t PYTHON_FILES < <(find "$ROOT_DIR/test-client" "$ROOT_DIR/e2e" "$ROOT_DIR/tests" -type f -name '*.py' -print)
flake8 "${PYTHON_FILES[@]}"
python3 -m compileall -q "${PYTHON_FILES[@]}"

while IFS= read -r shell_file; do
    bash -n "$shell_file"
done < <(find "$ROOT_DIR" -path "$ROOT_DIR/.git" -prune -o -path "$ROOT_DIR/.runtime" -prune -o -path "$ROOT_DIR/.build" -prune -o -type f -name '*.sh' -print)

python3 - "$ROOT_DIR" <<'PY'
import json
import pathlib
import sys
import xml.etree.ElementTree as ET

root = pathlib.Path(sys.argv[1])
json.loads((root / "config/realm-import.json").read_text(encoding="utf-8"))
ET.parse(root / "providers/oidc4ac-test-email/pom.xml")
PY

resolve_keycloak_repo "$ROOT_DIR" || die "unable to prepare the Keycloak implementation checkout"

MAVEN_IMAGE="${OIDC4AC_LAB_BUILDER_IMAGE:-maven:3.9-eclipse-temurin-21@sha256:c07f7ccfb8ca6c9fa29ee523f00afa7d2ca6132c92f8652c4aebb5ee3491f502}"
mkdir -p "$ROOT_DIR/.runtime/maven-cache"
docker run --rm \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$ROOT_DIR,dst=/workspace" \
    --mount "type=bind,src=$KEYCLOAK_REPO,dst=/keycloak-source" \
    --workdir /workspace \
    --env HOME=/tmp \
    --env MAVEN_CONFIG=/workspace/.runtime/maven-cache \
    --env MAVEN_OPTS=-Dmaven.repo.local=/workspace/.runtime/maven-cache/repository \
    --env DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    "$MAVEN_IMAGE" bash -lc '
        set -euo pipefail
        cd /keycloak-source
        ./mvnw -N -DskipTests install
        ./mvnw -pl server-spi-private -am -DskipTests install
        cd /workspace
        /keycloak-source/mvnw -f providers/oidc4ac-test-email/pom.xml -DskipTests spotless:check
    '

echo "Lint checks passed."
