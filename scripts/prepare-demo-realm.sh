#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${1:-"$ROOT_DIR/deploy/demo/demo.env"}
OUTPUT_FILE=${2:-"$ROOT_DIR/.runtime/demo/realm-import.json"}

[[ -f "$ENV_FILE" ]] || {
    echo "Demo environment file not found: $ENV_FILE" >&2
    echo "Copy deploy/demo/demo.env.example to deploy/demo/demo.env and edit it." >&2
    exit 1
}
command -v jq >/dev/null 2>&1 || {
    echo "jq is required to prepare the hosted demo realm." >&2
    exit 1
}

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${OIDC4AC_DEMO_CLIENT_URL:?Missing OIDC4AC_DEMO_CLIENT_URL}"

if [[ -d "$OUTPUT_FILE" ]]; then
    echo "Realm output path is a directory: $OUTPUT_FILE" >&2
    echo "Remove that empty Docker-created directory and run this script again." >&2
    exit 1
fi

mkdir -p "$(dirname -- "$OUTPUT_FILE")"
jq \
    --arg client_url "${OIDC4AC_DEMO_CLIENT_URL%/}" \
    '(.smtpServer.host = "127.0.0.1")
     | (.smtpServer.port = "2525")
     | ((.clients[] | select(.clientId == "oidc4ac-test-client")) |=
        (.redirectUris = [$client_url + "/*"]
         | .webOrigins = [$client_url]
         | .rootUrl = $client_url
         | .baseUrl = $client_url
         | .attributes["post.logout.redirect.uris"] = ($client_url + "/*")))
     | ((.clients[] | select(.clientId == "oidc4ac-consent-test-client")) |=
        (.redirectUris = [$client_url + "/*"]
         | .webOrigins = [$client_url]))' \
    "$ROOT_DIR/config/realm-import.json" >"$OUTPUT_FILE"

echo "Prepared hosted demo realm: $OUTPUT_FILE"
