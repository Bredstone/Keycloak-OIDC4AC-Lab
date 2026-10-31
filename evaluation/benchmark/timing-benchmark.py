"""Controlled, local timing of OIDC4AC across a chain of configurations.

Run this file inside the laboratory's HTTP test image, where run.py is
available (see run-benchmark.sh). Each round measures three kinds of cycle in
random order:

- sso: a warm-SSO authorization (RP login endpoint, authorization response,
  token exchange, and UserInfo), in which the session cookie authenticates the
  user and no form is shown;
- refresh: the RP's refresh endpoint (refresh-token grant and UserInfo);
- login: an interactive login without a session, automated with a
  password-only user (username form, password form, token exchange, and
  UserInfo); the session it creates is ended afterwards, outside the measured
  interval.

The client-observed duration is measured around the cycle; the server-side
duration is the increase of Keycloak's HTTP server request time during the
cycle, read from its metrics endpoint before and after the cycle. The SSO
session of the full-request condition, which needs WebAuthn and email factors,
is established in the browser by seed-session.py; its Keycloak cookies are
loaded here, so no factor is collected in its sso and refresh cycles, and it
has no login cycle. Every instance serves the same number of cycles of each
kind per round, so that no instance stays idle, and therefore colder, more
often than another. It is not a production load test and it does not time
human factor collection.
"""

from __future__ import annotations

import json
import os
import platform
import random
import re
import time
from dataclasses import dataclass, replace
from itertools import cycle as repeat
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

import run


WARMUPS = int(os.environ.get("OIDC4AC_BENCHMARK_WARMUPS", "50"))
SAMPLES = int(os.environ.get("OIDC4AC_BENCHMARK_SAMPLES", "100"))
SEED = Path(os.environ.get("OIDC4AC_BENCHMARK_SEED", "/tmp/oidc4ac-seed-session.json"))
RUN_ID = int(os.environ.get("OIDC4AC_BENCHMARK_RUN", "1"))
OUTPUT = Path(os.environ.get("OIDC4AC_BENCHMARK_OUTPUT", "/tmp/oidc4ac-benchmark-results.json"))
SERVER_TIME = re.compile(r'^http_server_requests_seconds_sum\{(.*)\}\s+(\S+)$', re.MULTILINE)
LOGIN_USER = ("otp-user", "Otp-user-password-123")
KINDS = ("sso", "refresh", "login")


@dataclass(frozen=True)
class Condition:
    name: str
    client: str
    issuer: str
    metrics: str
    request_claims: dict[str, Any]
    omit_claims: bool
    expects_details: bool
    login: bool = True


CONDITIONS = (
    Condition("keycloak_official", "http://localhost:5007",
              "http://localhost:8188/realms/oidc4ac", "http://localhost:9188/metrics", {}, True, False),
    Condition("fork_feature_disabled", "http://localhost:5006",
              "http://localhost:8187/realms/oidc4ac", "http://localhost:9187/metrics", {}, True, False),
    Condition("fork_realm_disabled", "http://localhost:5005",
              "http://localhost:8186/realms/oidc4ac-off", "http://localhost:9186/metrics", {}, True, False),
    Condition("oidc4ac_without_request", "http://localhost:5003",
              "http://localhost:8186/realms/oidc4ac", "http://localhost:9186/metrics", {}, True, False),
    Condition("oidc4ac_with_request", "http://localhost:5003",
              "http://localhost:8186/realms/oidc4ac", "http://localhost:9186/metrics",
              run.claims(run.method("pwd")), False, True),
    # Its request and SSO session come from seed-session.py: every advertised
    # method with every advertised metadata member and property.
    Condition("oidc4ac_with_full_request", "http://localhost:5003",
              "http://localhost:8186/realms/oidc4ac", "http://localhost:9186/metrics", {}, False, True,
              login=False),
)


def configure(condition: Condition) -> None:
    run.CLIENT = condition.client
    run.ISSUER = condition.issuer


def server_seconds(condition: Condition) -> float:
    """Total request time recorded by the instance, excluding metrics scrapes."""
    text = requests.get(condition.metrics, timeout=15).text
    return sum(float(value) for labels, value in SERVER_TIME.findall(text) if 'uri="/metrics"' not in labels)


def check_projection(condition: Condition, result: run.AuthorizationResult) -> None:
    id_token = result.json_section("Verified ID Token")
    userinfo = result.json_section("Access-token-bound UserInfo")
    has_details = "amr_details" in id_token and "amr_details" in userinfo
    if has_details != condition.expects_details:
        raise AssertionError(f"{condition.name}: unexpected amr_details projection.")


def authorize(condition: Condition, session: requests.Session, *, prompt_login: bool) -> run.AuthorizationResult:
    configure(condition)
    result = run.authorize(
        condition.request_claims,
        session=session,
        prompt_login=prompt_login,
        omit_claims=condition.omit_claims,
    ).require_success()
    check_projection(condition, result)
    if not prompt_login and result.forms:
        raise AssertionError(f"{condition.name}: warm SSO unexpectedly rendered {result.forms!r}.")
    return result


class Admin:
    """Ends the login user's sessions through each instance's admin API."""

    def __init__(self) -> None:
        self.tokens: dict[str, tuple[float, str]] = {}
        self.users: dict[str, str] = {}

    def headers(self, base: str) -> dict[str, str]:
        issued, token = self.tokens.get(base, (0.0, ""))
        if time.monotonic() - issued > 45:
            response = requests.post(f"{base}/realms/master/protocol/openid-connect/token", data={
                "grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin",
            }, timeout=15)
            response.raise_for_status()
            token = response.json()["access_token"]
            self.tokens[base] = (time.monotonic(), token)
        return {"Authorization": f"Bearer {token}"}

    def logout(self, condition: Condition) -> None:
        base, realm = condition.issuer.split("/realms/", 1)
        if condition.issuer not in self.users:
            users = requests.get(f"{base}/admin/realms/{realm}/users", params={"username": LOGIN_USER[0], "exact": "true"},
                                 headers=self.headers(base), timeout=15).json()
            self.users[condition.issuer] = users[0]["id"]
        response = requests.post(f"{base}/admin/realms/{realm}/users/{self.users[condition.issuer]}/logout",
                                 headers=self.headers(base), timeout=15)
        response.raise_for_status()


def sso_cycle(condition: Condition, sessions: dict[str, requests.Session]) -> None:
    authorize(condition, sessions[condition.name], prompt_login=False)


def refresh_cycle(condition: Condition, sessions: dict[str, requests.Session]) -> None:
    session = sessions[condition.name]
    response = session.post(f"{condition.client}/refresh", allow_redirects=True, timeout=15)
    result = run.AuthorizationResult(session, response, []).require_success()
    if "Refresh token response" not in response.text:
        raise AssertionError(f"{condition.name}: the test client did not render a refresh response.")
    check_projection(condition, result)


def login_cycle(condition: Condition, sessions: dict[str, requests.Session]) -> None:
    configure(condition)
    run.ALICE, run.PASSWORD = LOGIN_USER
    try:
        result = run.authorize(condition.request_claims, session=requests.Session(), prompt_login=True,
                               omit_claims=condition.omit_claims).require_success()
    finally:
        run.ALICE, run.PASSWORD = ALICE
    if result.forms != ["kc-form-login"]:
        raise AssertionError(f"{condition.name}: login crossed {result.forms!r} instead of the password form.")
    check_projection(condition, result)


CYCLES: dict[str, Callable[[Condition, dict[str, requests.Session]], None]] = {
    "sso": sso_cycle, "refresh": refresh_cycle, "login": login_cycle,
}
ALICE = (run.ALICE, run.PASSWORD)


def balanced_slots(conditions: tuple[Condition, ...]) -> list[tuple[str, Condition]]:
    """Repeats conditions so that every instance serves the same cycles per kind."""
    slots: list[tuple[str, Condition]] = []
    for kind in KINDS:
        included = [condition for condition in conditions if kind != "login" or condition.login]
        by_instance: dict[str, list[Condition]] = {}
        for condition in included:
            by_instance.setdefault(condition.metrics, []).append(condition)
        target = max(len(group) for group in by_instance.values())
        for group in by_instance.values():
            source = repeat(group)
            slots.extend((kind, next(source)) for _ in range(target))
    return slots


def compact_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def sizes_of(condition: Condition, result: run.AuthorizationResult, discovery_bytes: int) -> dict[str, int]:
    id_token = result.json_section("Verified ID Token")
    userinfo = result.json_section("Access-token-bound UserInfo")
    query = 0 if condition.omit_claims else len(urlencode(
        {"claims": json.dumps(condition.request_claims, separators=(",", ":"))}).encode("utf-8"))
    return {
        "discovery_response_bytes": discovery_bytes,
        "extension_request_query_bytes": query,
        "id_token_amr_details_bytes": compact_bytes(id_token["amr_details"]) if "amr_details" in id_token else 0,
        "userinfo_amr_details_bytes": compact_bytes(userinfo["amr_details"]) if "amr_details" in userinfo else 0,
        "id_token_payload_bytes": compact_bytes(id_token),
        "userinfo_response_bytes": compact_bytes(userinfo),
    }


def main() -> int:
    if WARMUPS < 1 or SAMPLES < 2:
        raise ValueError("At least one warm-up and two samples are required.")
    # Avoid the runner's intentional first-run TOTP delay; seed logins that
    # require OTP still wait for a fresh code.
    run.LAST_TOTP_COUNTER = -1
    order = random.Random(RUN_ID)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    conditions = CONDITIONS[:-1] + (replace(CONDITIONS[-1], request_claims=seed["request_claims"]),)
    full_request = conditions[-1]
    slots = balanced_slots(conditions)
    admin = Admin()

    sessions: dict[str, requests.Session] = {}
    sizes: dict[str, dict[str, int]] = {}
    for condition in conditions:
        if condition is full_request:
            session = requests.Session()
            for cookie in seed["cookies"]:
                # requests stores a bare localhost host as localhost.local.
                domain = cookie["domain"].lstrip(".")
                session.cookies.set_cookie(requests.cookies.create_cookie(
                    cookie["name"], cookie["value"], path=cookie["path"],
                    domain=domain if "." in domain else f"{domain}.local"))
            result = authorize(condition, session, prompt_login=False)
            requested = {method["amr_identifier"]["value"]
                         for method in condition.request_claims["id_token"]["amr_details"]["all_of"]}
            executed = set(run.detail_map(result.json_section("Verified ID Token")))
            run.check(executed == requested, f"Full request reported {sorted(executed)}.")
        else:
            session = requests.Session()
            result = authorize(condition, session, prompt_login=True)
        sessions[condition.name] = session
        discovery = requests.get(f"{condition.issuer}/.well-known/openid-configuration", timeout=15)
        discovery.raise_for_status()
        sizes[condition.name] = sizes_of(condition, result, len(discovery.content))

    def execute(kind: str, condition: Condition) -> None:
        CYCLES[kind](condition, sessions)
        if kind == "login":
            admin.logout(condition)

    for _ in range(WARMUPS):
        for kind, condition in order.sample(slots, len(slots)):
            execute(kind, condition)

    samples: dict[str, dict[str, list[dict[str, Any]]]] = {
        kind: {condition.name: [] for condition in conditions if kind != "login" or condition.login} for kind in KINDS
    }
    for round_index in range(SAMPLES):
        for position, (kind, condition) in enumerate(order.sample(slots, len(slots))):
            before = server_seconds(condition)
            started = time.perf_counter()
            CYCLES[kind](condition, sessions)
            client_ms = (time.perf_counter() - started) * 1000
            server_ms = (server_seconds(condition) - before) * 1000
            if kind == "login":
                admin.logout(condition)
            samples[kind][condition.name].append({
                "round": round_index,
                "position": position,
                "client_ms": round(client_ms, 4),
                "server_ms": round(server_ms, 4),
            })

    result = {
        "scope": "local sso, refresh, and login cycles; not a production benchmark or human-authentication measurement",
        "run": RUN_ID,
        "warmup_rounds": WARMUPS,
        "measured_rounds": SAMPLES,
        "cycles_per_round": len(slots),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "cpu_frequency": os.environ.get("OIDC4AC_BENCHMARK_CPU_FREQUENCY", ""),
            "cpusets": {key: os.environ.get(key, "") for key in (
                "KC_OFFICIAL_CPUS", "KC_DISABLED_CPUS", "KC_ENABLED_CPUS", "CLIENT_CPUS")},
        },
        "full_request_claims": full_request.request_claims,
        "sizes": sizes,
        "samples": samples,
    }
    OUTPUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"run {RUN_ID}: {SAMPLES} rounds of {len(slots)} cycles written to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
