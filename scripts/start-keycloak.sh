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
REPOSITORY_DIR=$(CDPATH= cd -- "${OIDC4AC_LAB_KEYCLOAK_REPO:-$LAB_DIR/../keycloak-OIDC4AC}" && pwd)
RUNTIME_DIR="$LAB_DIR/.runtime"
BUILD_DIR="$LAB_DIR/.build"
ARCHIVE="$REPOSITORY_DIR/quarkus/dist/target/keycloak-26.7.0.tar.gz"
HTTP_PORT="${OIDC4AC_LAB_HTTP_PORT:-8080}"

mkdir -p "$RUNTIME_DIR"
if [[ "${OIDC4AC_LAB_SKIP_BUILD:-false}" != "true" ]]; then
    "$REPOSITORY_DIR/mvnw" -pl quarkus/dist -am -DskipTests -Dskip.pnpm=true package
fi

if [[ ! -f "$ARCHIVE" ]]; then
    echo "Expected distribution archive was not produced: $ARCHIVE" >&2
    exit 1
fi

mkdir -p "$BUILD_DIR"
cp "$ARCHIVE" "$BUILD_DIR/keycloak-26.7.0.tar.gz"

KEYCLOAK_HOME=$(mktemp -d "$RUNTIME_DIR/keycloak.XXXXXX")
tar -xzf "$ARCHIVE" -C "$KEYCLOAK_HOME" --strip-components=1
mkdir -p "$KEYCLOAK_HOME/data/import"
cp "$LAB_DIR/config/realm-import.json" "$KEYCLOAK_HOME/data/import/oidc4ac-realm.json"

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
