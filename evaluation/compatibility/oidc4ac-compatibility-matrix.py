"""Compatibility matrix for the local OIDC4AC reference laboratory.

Run this file from the laboratory's e2e/http directory, where run.py is
available. It exercises request and fallback behavior; it does not test an
independently developed RP.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

import run


@dataclass(frozen=True)
class Endpoint:
    client: str
    issuer: str


ENABLED = Endpoint(
    client="http://localhost:5003",
    issuer="http://localhost:8186/realms/oidc4ac",
)
DISABLED = Endpoint(
    client="http://client.localhost:5001",
    issuer="http://localhost:8187/realms/oidc4ac",
)


def configure(endpoint: Endpoint) -> None:
    run.CLIENT = endpoint.client
    run.ISSUER = endpoint.issuer


def discovery(endpoint: Endpoint) -> dict:
    response = requests.get(
        f"{endpoint.issuer}/.well-known/openid-configuration", timeout=15
    )
    run.check(response.status_code == 200, f"Discovery returned HTTP {response.status_code}.")
    return response.json()


def has_details(result: run.AuthorizationResult) -> bool:
    return (
        "amr_details" in result.json_section("Verified ID Token")
        or "amr_details" in result.json_section("Access-token-bound UserInfo")
    )


def ordinary_success(
    endpoint: Endpoint,
    label: str,
    *,
    session: requests.Session | None = None,
    prompt_login: bool = True,
) -> run.AuthorizationResult:
    configure(endpoint)
    result = run.authorize(
        {},
        session=session,
        prompt_login=prompt_login,
        omit_claims=True,
    ).require_success()
    run.check(
        not has_details(result),
        f"{label}: an ordinary OIDC request unexpectedly received amr_details.",
    )
    return result


def main() -> int:
    # Avoid the runner's intentional first-run TOTP delay. The fixed test code
    # remains valid and the OTP form is still submitted when the disabled OP
    # requires it.
    run.LAST_TOTP_COUNTER = -1
    print("START legacy RP / legacy OP", flush=True)

    legacy_metadata = discovery(DISABLED)
    run.check(
        "amr_details" not in legacy_metadata.get("claims_supported", []),
        "Legacy OP advertised amr_details.",
    )
    legacy = ordinary_success(DISABLED, "legacy RP / legacy OP")
    print("PASS legacy RP / legacy OP: ordinary success, no extension claim")

    enabled_metadata = discovery(ENABLED)
    run.check(
        "amr_details" in enabled_metadata.get("claims_supported", []),
        "OIDC4AC OP did not advertise amr_details.",
    )
    print("START legacy RP / OIDC4AC OP", flush=True)
    ordinary_success(ENABLED, "legacy RP / OIDC4AC OP")
    print("PASS legacy RP / OIDC4AC OP: ordinary success, no extension claim")

    print("START OIDC4AC RP / legacy OP fallback", flush=True)
    fallback = ordinary_success(
        DISABLED,
        "OIDC4AC RP / legacy OP fallback",
        session=legacy.session,
        prompt_login=False,
    )
    print("START direct structured request to legacy OP", flush=True)
    direct = run.authorize(
        run.claims(run.method("pwd")),
        session=fallback.session,
        prompt_login=False,
    ).require_success()
    run.check(
        not has_details(direct),
        "OIDC4AC RP / legacy OP: legacy OP emitted amr_details.",
    )
    print("PASS OIDC4AC RP / legacy OP: Discovery-guided fallback; direct request remains ordinary")

    print("START OIDC4AC RP / OIDC4AC OP", flush=True)
    configure(ENABLED)
    extended = run.authorize(run.claims(run.method("pwd"))).require_success()
    id_token = extended.json_section("Verified ID Token")
    userinfo = extended.json_section("Access-token-bound UserInfo")
    run.check(
        "amr_details" in id_token and "amr_details" in userinfo,
        "OIDC4AC RP / OIDC4AC OP did not deliver amr_details in both locations.",
    )
    run.check(
        id_token["amr_details"][0]["amr_identifier"] == "pwd"
        and userinfo["amr_details"][0]["amr_identifier"] == "pwd",
        "OIDC4AC RP / OIDC4AC OP did not report the requested pwd method.",
    )
    print("PASS OIDC4AC RP / OIDC4AC OP: structured request processed and projected")

    print("START OIDC4AC RP / informational-only OP", flush=True)
    use_flow_without_planner(ENABLED)
    informational_metadata = discovery(ENABLED)
    run.check(
        "amr_details" in informational_metadata.get("claims_supported", [])
        and informational_metadata.get("amr_details_request_supported") is False,
        "Informational-only OP did not advertise amr_details without request-processing support.",
    )
    configure(ENABLED)
    # The request requires pop, which the built-in browser flow never executes.
    # An informational-only OP ignores the expression and reports what occurred.
    informational = run.authorize(run.claims(run.method("pop"))).require_success()
    executed = set(run.detail_map(informational.json_section("Verified ID Token")))
    run.check(
        "pwd" in executed and "pop" not in executed,
        f"Informational-only OP reported {sorted(executed)} instead of the executions that occurred.",
    )
    print("PASS OIDC4AC RP / informational-only OP: request ignored, actual executions reported")
    return 0


def use_flow_without_planner(endpoint: Endpoint) -> None:
    """Bind the realm to Keycloak's built-in browser flow, which has no planner."""
    base = endpoint.issuer.rsplit("/realms/", 1)[0]
    token = requests.post(f"{base}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin",
    }, timeout=15)
    run.check(token.status_code == 200, "Could not obtain an admin token.")
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    realm_url = f"{base}/admin/realms/oidc4ac"
    realm = requests.get(realm_url, headers=headers, timeout=15).json()
    realm["browserFlow"] = "browser"
    update = requests.put(realm_url, headers=headers, json=realm, timeout=15)
    run.check(update.status_code in {200, 204}, f"Could not bind the built-in browser flow: HTTP {update.status_code}.")


if __name__ == "__main__":
    raise SystemExit(main())
