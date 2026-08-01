#!/usr/bin/env bash
#
# Copyright 2026 Red Hat, Inc. and/or its affiliates
# and other contributors as indicated by the @author tags.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LAB_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
source "$LAB_DIR/scripts/keycloak-repo.sh"
resolve_keycloak_repo "$LAB_DIR" || exit 1
REPOSITORY_DIR="$KEYCLOAK_REPO"
RUNTIME_DIR="$LAB_DIR/.runtime"
BUILD_DIR="$LAB_DIR/.build"
PREPARED_ARCHIVE="$BUILD_DIR/keycloak-26.7.0.tar.gz"
PROVIDER_JAR="$LAB_DIR/providers/oidc4ac-test-email/target/oidc4ac-test-email-1.0.0-SNAPSHOT.jar"
HTTP_PORT="${OIDC4AC_LAB_HTTP_PORT:-8080}"

mkdir -p "$RUNTIME_DIR"
if [[ -f "$PREPARED_ARCHIVE" ]]; then
    ARCHIVE="$PREPARED_ARCHIVE"
else
    echo "Keycloak distribution archive is missing." >&2
    echo "Run './dev.sh build' to fetch and compile Keycloak in Docker before starting it." >&2
    exit 1
fi
if [[ ! -f "$PROVIDER_JAR" ]]; then
    echo "The email provider JAR is missing: $PROVIDER_JAR" >&2
    echo "Run './dev.sh provider-build' before starting Keycloak." >&2
    exit 1
fi

mkdir -p "$BUILD_DIR"
if [[ "$ARCHIVE" != "$PREPARED_ARCHIVE" ]]; then
    cp "$ARCHIVE" "$PREPARED_ARCHIVE"
fi

KEYCLOAK_HOME=$(mktemp -d "$RUNTIME_DIR/keycloak.XXXXXX")
tar -xzf "$ARCHIVE" -C "$KEYCLOAK_HOME" --strip-components=1
mkdir -p "$KEYCLOAK_HOME/data/import"
cp "$LAB_DIR/config/realm-import.json" "$KEYCLOAK_HOME/data/import/oidc4ac-realm.json"
mkdir -p "$KEYCLOAK_HOME/providers"
cp "$PROVIDER_JAR" "$KEYCLOAK_HOME/providers/"

export KC_BOOTSTRAP_ADMIN_USERNAME="${OIDC4AC_LAB_ADMIN_USERNAME:-admin}"
export KC_BOOTSTRAP_ADMIN_PASSWORD="${OIDC4AC_LAB_ADMIN_PASSWORD:-admin}"

echo "Starting native OIDC4AC lab at http://keycloak.localhost:$HTTP_PORT"
echo "Administration: $KC_BOOTSTRAP_ADMIN_USERNAME / (the configured local password)"
exec "$KEYCLOAK_HOME/bin/kc.sh" start-dev \
    --features=oidc4ac:v1,admin-fine-grained-authz:v2 \
    --import-realm \
    --http-host=0.0.0.0 \
    --http-port="$HTTP_PORT" \
    --hostname="http://keycloak.localhost:$HTTP_PORT" \
    --hostname-strict=false
