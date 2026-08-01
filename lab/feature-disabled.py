"""Server-level regression for a Keycloak process started without oidc4ac."""

from __future__ import annotations

import os
import requests


ISSUER = os.environ.get("OIDC4AC_DISABLED_ISSUER", "http://localhost:8187/realms/oidc4ac").rstrip("/")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    discovery = requests.get(f"{ISSUER}/.well-known/openid-configuration", timeout=15)
    check(discovery.status_code == 200, f"Disabled-feature discovery returned HTTP {discovery.status_code}.")
    metadata = discovery.json()
    check("amr_details" not in metadata.get("claims_supported", []),
          "Disabled OIDC4AC unexpectedly advertised amr_details support.")
    check("amr_identifiers_supported" not in metadata,
          "Disabled OIDC4AC unexpectedly advertised method capabilities.")

    admin = requests.post("http://localhost:8187/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": "admin",
        "password": "admin",
    }, timeout=15)
    check(admin.status_code == 200, "Could not obtain the disabled-server admin token.")
    headers = {"Authorization": f"Bearer {admin.json()['access_token']}", "Content-Type": "application/json"}
    realm = requests.get("http://localhost:8187/admin/realms/oidc4ac", headers=headers, timeout=15).json()
    realm["browserFlow"] = "browser"
    update = requests.put("http://localhost:8187/admin/realms/oidc4ac", headers=headers, json=realm, timeout=15)
    check(update.status_code in {204, 200}, f"Could not bind the built-in browser flow: HTTP {update.status_code}.")

    response = requests.get(f"{ISSUER}/protocol/openid-connect/auth", params={
        "response_type": "code",
        "client_id": "oidc4ac-test-client",
        "redirect_uri": "http://localhost:5003/callback",
        "scope": "openid",
        "state": "feature-disabled-state",
        "nonce": "feature-disabled-nonce",
        "claims": '{"id_token":{"amr_details":{"amr_identifier":{"value":"pwd"}}}}',
    }, allow_redirects=False, timeout=15)
    # The ordinary OIDC endpoint remains available; the experimental parser is
    # not allowed to turn a disabled feature into an OIDC4AC invalid_request.
    check(response.status_code in {200, 302}, f"Disabled-feature authorization returned HTTP {response.status_code}.")
    check("unmet_authentication_requirements" not in response.text,
          "Disabled OIDC4AC emitted its experimental authentication error.")
    print("PASS feature-disabled discovery and authorization regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
