#!/usr/bin/env bash

# Resolve the Keycloak implementation used by the lab. The caller must define
# ROOT_DIR and may provide a die() function for user-facing failures.

resolve_keycloak_repo() {
    local lab_dir=$1
    local configured=${OIDC4AC_LAB_KEYCLOAK_REPO:-}
    local sibling="$lab_dir/../keycloak-OIDC4AC"
    local checkout

    if [[ -n "$configured" ]]; then
        checkout="$configured"
        if [[ "$checkout" != /* ]]; then
            checkout="$lab_dir/$checkout"
        fi
        if [[ ! -x "$checkout/mvnw" ]]; then
            echo "Keycloak checkout not found or mvnw is not executable: $checkout" >&2
            return 1
        fi
        KEYCLOAK_REPO=$(CDPATH= cd -- "$checkout" && pwd)
        export KEYCLOAK_REPO
        return 0
    fi

    if [[ -x "$sibling/mvnw" ]]; then
        KEYCLOAK_REPO=$(CDPATH= cd -- "$sibling" && pwd)
        export KEYCLOAK_REPO
        return 0
    fi

    command -v git >/dev/null 2>&1 || {
        echo "git is required to download the Keycloak implementation checkout." >&2
        return 1
    }

    local runtime_dir="$lab_dir/.runtime"
    checkout="$runtime_dir/keycloak-source"
    mkdir -p "$runtime_dir"

    if [[ -e "$checkout" && ! -x "$checkout/mvnw" ]]; then
        echo "Keycloak source directory exists but is incomplete: $checkout" >&2
        return 1
    fi

    if [[ ! -e "$checkout" ]]; then
        local url=${OIDC4AC_LAB_KEYCLOAK_REPO_URL:-https://github.com/Bredstone/keycloak-OIDC4AC.git}
        local ref=${OIDC4AC_LAB_KEYCLOAK_REF:-oidc4ac-implementation}
        echo "Downloading Keycloak implementation from $url ($ref)..." >&2
        if [[ -n "$ref" ]]; then
            git clone --depth 1 --branch "$ref" "$url" "$checkout"
        else
            git clone --depth 1 "$url" "$checkout"
        fi
    fi

    KEYCLOAK_REPO=$(CDPATH= cd -- "$checkout" && pwd)
    export KEYCLOAK_REPO
}
