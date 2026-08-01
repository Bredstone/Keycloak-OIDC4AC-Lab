#!/usr/bin/env bash

# Resolve the Keycloak implementation used by the lab. The caller must define
# ROOT_DIR and may provide a die() function for user-facing failures.

resolve_keycloak_repo() {
    local lab_dir=$1
    local configured=${OIDC4AC_LAB_KEYCLOAK_REPO:-}
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

    local url=${OIDC4AC_LAB_KEYCLOAK_REPO_URL:-https://github.com/Bredstone/keycloak-OIDC4AC.git}
    local ref=${OIDC4AC_LAB_KEYCLOAK_REF:-oidc4ac-implementation}

    if [[ ! -e "$checkout" ]]; then
        echo "Downloading Keycloak implementation from $url ($ref)..." >&2
        if [[ -n "$ref" ]]; then
            git clone --depth 1 --branch "$ref" "$url" "$checkout"
        else
            git clone --depth 1 "$url" "$checkout"
        fi
    else
        [[ -d "$checkout/.git" ]] || {
            echo "Keycloak source directory exists but is not a Git checkout: $checkout" >&2
            return 1
        }

        # This checkout is generated state, not a user workspace. Always
        # fetch the configured fork/ref so repeated lab runs cannot silently
        # reuse a stale implementation or distribution.
        echo "Fetching Keycloak implementation from $url ($ref)..." >&2
        git -C "$checkout" remote set-url origin "$url"
        if [[ -n "$ref" ]]; then
            git -C "$checkout" fetch --prune --depth 1 origin "$ref"
            git -C "$checkout" reset --hard FETCH_HEAD >/dev/null
        else
            git -C "$checkout" fetch --prune --depth 1 origin
            git -C "$checkout" remote set-head origin -a >/dev/null 2>&1 || true
            local default_ref
            default_ref=$(git -C "$checkout" symbolic-ref --quiet --short refs/remotes/origin/HEAD || true)
            [[ -n "$default_ref" ]] || {
                echo "Unable to determine the default branch for $url" >&2
                return 1
            }
            git -C "$checkout" reset --hard "$default_ref" >/dev/null
        fi
        git -C "$checkout" clean -fdx >/dev/null
    fi

    KEYCLOAK_REPO=$(CDPATH= cd -- "$checkout" && pwd)
    export KEYCLOAK_REPO
    echo "Using Keycloak source $(git -C "$checkout" rev-parse --short HEAD)" >&2
}
