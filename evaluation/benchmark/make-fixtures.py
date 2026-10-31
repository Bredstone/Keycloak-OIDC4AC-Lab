"""Derives the benchmark realm fixtures from the laboratory's realm import.

Usage: python3 make-fixtures.py <lab>/config/realm-import.json <output-dir>

The plain fixture keeps the laboratory's users, credentials, and clients but
replaces the OIDC4AC flows, so it imports into the official Keycloak
distribution and into the fork with the feature disabled. Its browser flow has
the laboratory flow's structure without the planner: the SSO cookie or, as
alternative, a username form followed by a password form. Interactive logins
therefore cross the same screens in every configuration. The realm-disabled
fixture is the same realm under another name, with OIDC4AC switched off for
that realm only.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

BENCHMARK_REDIRECTS = [f"http://localhost:{port}/*" for port in (5005, 5006, 5007)]


def execution(priority: int, authenticator: str | None = None, flow: str | None = None,
              requirement: str = "REQUIRED") -> dict:
    step = {"authenticatorFlow": flow is not None, "requirement": requirement,
            "priority": priority, "userSetupAllowed": False}
    step.update({"flowAlias": flow} if flow else {"authenticator": authenticator})
    return step


BROWSER_FLOWS = [
    {"alias": "benchmark browser", "description": "Laboratory browser flow without the OIDC4AC planner.",
     "providerId": "basic-flow", "topLevel": True, "builtIn": False,
     "authenticationExecutions": [execution(10, "auth-cookie", requirement="ALTERNATIVE"),
                                  execution(20, flow="benchmark browser forms", requirement="ALTERNATIVE")]},
    {"alias": "benchmark browser forms", "description": "Username form followed by a password form.",
     "providerId": "basic-flow", "topLevel": False, "builtIn": False,
     "authenticationExecutions": [execution(10, "auth-username-form"), execution(20, "auth-password-form")]},
]


def plain(realm: dict) -> dict:
    result = copy.deepcopy(realm)
    result.pop("authenticatorConfig", None)
    result["authenticationFlows"] = copy.deepcopy(BROWSER_FLOWS)
    result["browserFlow"] = "benchmark browser"
    result["attributes"] = {
        key: value for key, value in result.get("attributes", {}).items() if not key.startswith("oidc4ac.")
    }
    for client in result.get("clients", []):
        if client["clientId"] == "oidc4ac-test-client":
            client["redirectUris"] = client.get("redirectUris", []) + BENCHMARK_REDIRECTS
    return result


def without_ids(value):
    # The realm-disabled fixture shares a server with the laboratory realm,
    # so fixed identifiers such as the TOTP credential id would collide.
    if isinstance(value, dict):
        return {key: without_ids(item) for key, item in value.items() if key != "id"}
    if isinstance(value, list):
        return [without_ids(item) for item in value]
    return value


def main() -> int:
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    realm = json.loads(source.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)

    (output / "plain-realm.json").write_text(json.dumps(plain(realm), indent=2) + "\n", encoding="utf-8")

    realm_disabled = without_ids(plain(realm))
    realm_disabled["realm"] = "oidc4ac-off"
    realm_disabled["attributes"]["oidc4ac.enabled"] = "false"
    (output / "realm-disabled-realm.json").write_text(json.dumps(realm_disabled, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
