"""Measures OIDC4AC message sizes as they travel in the laboratory.

Run this file inside the laboratory's browser test image, where the browser
run.py is available (see run-message-sizes.sh). It sends the authentication
request itself, captures the code at the test client's redirect URI, exchanges
it at the token endpoint, and calls UserInfo, so it measures the encoded ID
Token, its decoded payload, and the UserInfo response body as Keycloak sends
them. It measures three cases: a baseline without amr_details; a single-method
case, which requests pwd; and an all-methods case, which requests, in one
all_of expression, every method advertised in Discovery, all completed in one
authentication (WebAuthn through a virtual authenticator, email through
smtp4dev). Both requests ask, for each method, for every advertised metadata
member and property, and ask for amr_details in the ID Token and in UserInfo.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.sync_api import Page, Request, sync_playwright

import run
from browser_flow import best_case, compact_bytes, complete_factors, new_session, open_browser, request_bytes, worst_case

OUTPUT = Path(os.environ.get("OIDC4AC_SIZES_OUTPUT", "/tmp/oidc4ac-message-sizes.json"))
CLIENT_ID = "oidc4ac-test-client"
CLIENT_SECRET = "oidc4ac-lab-client-secret"
SCOPE = "openid profile email"


def decode_segment(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def exchange(page: Page, request_claims: dict[str, Any] | None) -> tuple[str, bytes]:
    """Authenticates directly at Keycloak and returns the raw ID Token and UserInfo body."""
    endpoint = f"{run.KEYCLOAK}/realms/{run.REALM}/protocol/openid-connect"
    redirect_uri = f"{run.CLIENT}/callback"
    parameters = {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect_uri, "scope": SCOPE,
                  "state": secrets.token_urlsafe(16), "nonce": secrets.token_urlsafe(16)}
    if request_claims is not None:
        parameters["claims"] = json.dumps(request_claims, separators=(",", ":"))
    callbacks: list[str] = []

    def capture(request: Request) -> None:
        if request.url.startswith(redirect_uri):
            callbacks.append(request.url)

    # The test client rejects this callback, since it did not issue the state,
    # so the code remains unused for the exchange below.
    seen_messages = new_session(page)
    page.on("request", capture)
    try:
        page.goto(f"{endpoint}/auth?{urlencode(parameters)}", wait_until="domcontentloaded")
        complete_factors(page, seen_messages)
    finally:
        page.remove_listener("request", capture)
    code = parse_qs(urlparse(callbacks[-1]).query)["code"][0]
    tokens = page.request.post(f"{endpoint}/token", form={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
    })
    run.check(tokens.ok, f"Token endpoint returned HTTP {tokens.status}.")
    token_response = tokens.json()
    userinfo = page.request.get(f"{endpoint}/userinfo",
                                headers={"Authorization": f"Bearer {token_response['access_token']}"})
    run.check(userinfo.ok, f"UserInfo returned HTTP {userinfo.status}.")
    return token_response["id_token"], userinfo.body()


def measure(page: Page, request_claims: dict[str, Any] | None, expected: set[str]) -> dict[str, Any]:
    id_token, userinfo_body = exchange(page, request_claims)
    payload_bytes = decode_segment(id_token.split(".")[1])
    payload = json.loads(payload_bytes)
    userinfo = json.loads(userinfo_body)
    executed = set(run.detail_map(payload)) if expected else set()
    run.check(executed == expected, f"Executions were {sorted(executed)}, expected {sorted(expected)}.")
    run.check(payload.get("amr_details") == userinfo.get("amr_details"),
              "ID Token and UserInfo reported different events.")
    details = payload.get("amr_details", [])
    return {
        "request_claims": request_claims,
        "extension_request_query_bytes": request_bytes(request_claims) if request_claims else 0,
        "amr_details": details,
        "amr_details_bytes": compact_bytes(details) if details else 0,
        "id_token_payload_bytes": len(payload_bytes),
        "id_token_encoded_bytes": len(id_token.encode("ascii")),
        "userinfo_response_bytes": len(userinfo_body),
        "execution_entry_bytes": {entry["amr_identifier"]: compact_bytes(entry) for entry in details},
    }


def main() -> int:
    with sync_playwright() as playwright:
        browser, page, discovery = open_browser(playwright)
        result = {
            "baseline": measure(page, None, set()),
            "single_method": measure(page, best_case(discovery), {"pwd"}),
            "all_methods": measure(page, worst_case(discovery), set(discovery["amr_identifiers_supported"])),
        }
        browser.close()
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for case, values in result.items():
        print(case, json.dumps({key: value for key, value in values.items() if key.endswith("bytes")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
