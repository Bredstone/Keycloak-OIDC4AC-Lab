"""End-to-end OIDC4AC checks through the disposable Flask relying party.

The runner intentionally submits the test-client's /login form and follows
the real authorization-code redirect, rather than calling the token endpoint
or protocol internals directly. It therefore verifies the same client-visible
result pages used for manual experiments.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
import struct
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests


CLIENT = os.environ.get("OIDC4AC_E2E_CLIENT_URL", "http://client.localhost:5000").rstrip("/")
ISSUER = os.environ.get("OIDC4AC_E2E_ISSUER", "http://keycloak.localhost:8080/realms/oidc4ac").rstrip("/")
ALICE = os.environ.get("OIDC4AC_E2E_USERNAME", "alice")
PASSWORD = os.environ.get("OIDC4AC_E2E_PASSWORD", "Alice-password-123")
ADMIN_USERNAME = os.environ.get("OIDC4AC_E2E_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("OIDC4AC_E2E_ADMIN_PASSWORD", "admin")
TOTP_SECRET = os.environ.get("OIDC4AC_E2E_TOTP_SECRET", "DJmQfC73VGFhw7D4QJ8A")
SMTP4DEV = os.environ.get("OIDC4AC_E2E_SMTP4DEV_URL", "http://localhost:5080").rstrip("/")
TIMEOUT = float(os.environ.get("OIDC4AC_E2E_TIMEOUT", "90"))
LAST_TOTP_COUNTER: int | None = None


class CheckFailure(AssertionError):
    """An assertion whose context should be shown directly to the lab user."""


@dataclass
class Form:
    action: str
    values: dict[str, str]


class Forms(HTMLParser):
    """Small dependency-free parser for the Keycloak login forms used here."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: dict[str, Form] = {}
        self._current_id: str | None = None
        self._current_action = ""
        self._current_values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._current_id = attributes.get("id")
            self._current_action = attributes.get("action", "")
            self._current_values = {}
        elif tag in {"input", "button"} and self._current_id:
            name = attributes.get("name")
            if name:
                self._current_values[name] = attributes.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._current_id:
            self.forms[self._current_id] = Form(self._current_action, dict(self._current_values))
            self._current_id = None
            self._current_action = ""
            self._current_values = {}


@dataclass
class AuthorizationResult:
    session: requests.Session
    response: requests.Response
    forms: list[str]

    def json_section(self, heading: str) -> dict[str, Any]:
        escaped_heading = re.escape(heading)
        match = re.search(rf"<h2>{escaped_heading}</h2><pre>(.*?)</pre>", self.response.text, re.DOTALL)
        if not match:
            raise CheckFailure(f"Result page does not contain the {heading!r} JSON section.")
        try:
            return json.loads(html.unescape(match.group(1)))
        except json.JSONDecodeError as error:
            raise CheckFailure(f"{heading} was not valid JSON: {error}") from error

    def error(self) -> str | None:
        match = re.search(r'<section class="error-page">.*?<h1>(.*?)</h1>', self.response.text, re.DOTALL)
        return html.unescape(match.group(1)).strip() if match else None

    def require_success(self) -> "AuthorizationResult":
        if self.error() is not None:
            raise CheckFailure(f"Expected authorization success, received {self.error()!r}.")
        if "Verified authentication context" not in self.response.text:
            raise CheckFailure("Test client did not render an authorization result.")
        return self

    def require_error(self, expected: str) -> "AuthorizationResult":
        actual = self.error()
        if actual != expected:
            raise CheckFailure(f"Expected public error {expected!r}, received {actual!r}.")
        return self


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def method(identifier: str, *, properties: dict[str, Any] | None = None, max_age: int | None = None) -> dict[str, Any]:
    time_constraint: dict[str, Any] = {"essential": True}
    if max_age is not None:
        time_constraint["max_age"] = max_age
    result: dict[str, Any] = {
        "amr_identifier": {"value": identifier},
        "amr_metadata": {"time": time_constraint},
    }
    if properties:
        result["amr_properties"] = properties
    return result


def claims(expression: dict[str, Any], *, id_token: bool = True, userinfo: bool = True,
           essential: bool = True) -> dict[str, Any]:
    request = {"essential": essential, **expression}
    result: dict[str, Any] = {}
    if id_token:
        result["id_token"] = {"amr_details": request}
    if userinfo:
        result["userinfo"] = {"amr_details": request}
    return result


def current_totp() -> str:
    """Return the RFC 6238 code for the disposable lab credential."""
    global LAST_TOTP_COUNTER
    # The realm-import fixture deliberately uses Keycloak's legacy raw-secret
    # form (no credentialData.secretEncoding), so Keycloak authenticates with
    # these UTF-8 bytes rather than a Base32-decoded value.
    secret = TOTP_SECRET.encode("utf-8")
    counter = int(time.time()) // 30
    if LAST_TOTP_COUNTER is None or counter == LAST_TOTP_COUNTER:
        # Keycloak's normal OTP policy rejects reuse of a valid code. Several
        # independent scenarios use the same test credential, and another
        # runner process may have consumed the current code already. Always
        # start a fresh runner window, then wait again only between scenarios.
        time.sleep(30 - (time.time() % 30) + 0.25)
        counter = int(time.time()) // 30
    LAST_TOTP_COUNTER = counter
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{truncated % 1_000_000:06d}"


def parse_forms(page: str) -> dict[str, Form]:
    parser = Forms()
    parser.feed(page)
    return parser.forms


def post_form(session: requests.Session, response: requests.Response, form: Form, values: dict[str, str]) -> requests.Response:
    action = urljoin(response.url, form.action)
    data = {**form.values, **values}
    return session.post(action, data=data, allow_redirects=False, timeout=15)


def parse_first_form(page: str) -> Form:
    """Parse a consent form, whose Keycloak template intentionally has no id."""
    match = re.search(r"<form\b([^>]*)>(.*?)</form>", page, re.DOTALL | re.IGNORECASE)
    check(match is not None, "Keycloak displayed a page without a usable form.")
    attributes = dict(re.findall(r"([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*['\"]([^'\"]*)['\"]", match.group(1)))
    values = dict(re.findall(
        r"<input\b[^>]*\bname\s*=\s*['\"]([^'\"]+)['\"][^>]*\bvalue\s*=\s*['\"]([^'\"]*)['\"]",
        match.group(2),
        re.IGNORECASE,
    ))
    return Form(attributes.get("action", ""), values)


def decode_unverified_jwt_payload(encoded: str) -> dict[str, Any]:
    """Decode a JARM payload for a local protocol-shape assertion.

    The test does not use this payload as an authentication result. Signature
    verification belongs to the relying party; this helper only checks that
    Keycloak delivered the expected public error inside the response JWT.
    """
    parts = encoded.split(".")
    check(len(parts) == 3, "The JARM response was not a compact JWT.")
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckFailure(f"The JARM response payload was not valid JSON: {error}") from error
    check(isinstance(decoded, dict), "The JARM response payload was not a JSON object.")
    return decoded


def direct_authorization(request_parameters: dict[str, str], *, cancel_consent: bool = False) -> requests.Response:
    """Drive a direct authorization request for endpoint-validation tests."""
    session = requests.Session()
    response = session.get(f"{ISSUER}/protocol/openid-connect/auth", params=request_parameters,
                           allow_redirects=False, timeout=15)
    for _ in range(16):
        allow_loopback_secure_cookies(session)
        if response.is_redirect:
            location = response.headers.get("Location")
            check(location is not None, "Authorization redirect did not include Location.")
            if urlparse(urljoin(response.url, location)).path.endswith("/callback"):
                return response
            response = session.get(urljoin(response.url, location), allow_redirects=False, timeout=15)
            continue

        forms = parse_forms(response.text)
        if "kc-form-login" in forms:
            login_form = forms["kc-form-login"]
            values = {"username": ALICE}
            if "password" in login_form.values:
                values["password"] = PASSWORD
            response = post_form(session, response, login_form, values)
            continue
        if cancel_consent and "kc-oauth" in response.text:
            response = post_form(session, response, parse_first_form(response.text), {"cancel": ""})
            return response
        if response.status_code == 200 and "error" in response.text and "/callback" in response.text:
            return response
        page_summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text)).strip()[:240]
        raise CheckFailure(f"Unexpected direct authorization page HTTP {response.status_code}: {page_summary!r}.")
    raise CheckFailure("Direct authorization did not reach a terminal response.")


def admin_token() -> str:
    base = ISSUER.split("/realms/", 1)[0]
    response = requests.post(f"{base}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    }, timeout=15)
    check(response.status_code == 200, f"Admin token endpoint returned HTTP {response.status_code}.")
    token = response.json().get("access_token")
    check(isinstance(token, str) and token, "Admin token response did not contain an access token.")
    return token


def allow_loopback_secure_cookies(session: requests.Session) -> None:
    """Match browser handling of Secure cookies on the special .localhost name.

    Chromium treats localhost and its subdomains as secure contexts even over
    HTTP. requests deliberately does not, so without this small test-driver
    adjustment Keycloak's HTTP-only local session cookies are never returned
    to its login action. This never affects a non-local host.
    """
    for cookie in session.cookies:
        # http.cookiejar normalises a bare localhost host to localhost.local
        # (the browser still treats it as a secure context).  Match the
        # normalised form as well as the explicit lab hostnames.
        if cookie.domain in {"keycloak.localhost", "localhost", "localhost.local"}:
            cookie.secure = False


def smtp_messages() -> list[dict[str, Any]]:
    response = requests.get(f"{SMTP4DEV}/api/messages", timeout=15)
    check(response.status_code == 200, f"smtp4dev message API returned HTTP {response.status_code}.")
    payload = response.json()
    if isinstance(payload, list):
        messages = payload
    elif isinstance(payload, dict):
        messages = payload.get("results") or payload.get("messages") or payload.get("items") or []
    else:
        messages = []
    check(isinstance(messages, list), "smtp4dev message API did not return a message list.")
    return [message for message in messages if isinstance(message, dict)]


def smtp_message_key(message: dict[str, Any]) -> str:
    return str(message.get("id") or message.get("guid") or json.dumps(message, sort_keys=True))


def smtp_verification_code(previous_messages: set[str]) -> str:
    """Wait for the code emitted by the email authenticator."""
    def extract_code(body: str) -> str | None:
        patterns = (
            r"verification code\s+is\s*:\s*(\d{6})",
            r"verification code\s+is\s+<[^>]+>\s*(\d{6})",
        )
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1)
        return None

    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        for message in smtp_messages():
            if smtp_message_key(message) in previous_messages:
                continue
            if "OIDC4AC verification code" not in json.dumps(message):
                continue
            detail = message
            message_id = message.get("id") or message.get("guid")
            if message_id is not None:
                encoded_id = quote(str(message_id), safe='')
                raw_response = requests.get(f"{SMTP4DEV}/api/messages/{encoded_id}/raw", timeout=15)
                if raw_response.status_code == 200:
                    code = extract_code(raw_response.text)
                    if code:
                        return code
                detail_response = requests.get(f"{SMTP4DEV}/api/messages/{encoded_id}", timeout=15)
                if detail_response.status_code == 200:
                    candidate = detail_response.json()
                    if isinstance(candidate, dict):
                        detail = candidate
            code = extract_code(json.dumps(detail))
            if code:
                return code
        time.sleep(1)
    raise CheckFailure("smtp4dev did not receive an OIDC4AC verification code within the test timeout.")


def clear_keycloak_cookies(session: requests.Session) -> None:
    """Drop only the issuer SSO cookies, retaining the RP's Flask session."""
    for cookie in list(session.cookies):
        if "keycloak" in (cookie.domain or ""):
            session.cookies.clear(cookie.domain, cookie.path, cookie.name)


def authorize(request_claims: dict[str, Any], *, session: requests.Session | None = None,
              prompt_login: bool = True, omit_claims: bool = False,
              offline_access: bool = False, use_email_code: bool = False) -> AuthorizationResult:
    """Drive the test client, Keycloak login form, OTP form, and callback."""
    session = session or requests.Session()
    previous_smtp_messages = {smtp_message_key(message) for message in smtp_messages()} if use_email_code else set()
    data: dict[str, str] = {"prompt_login": "on"} if prompt_login else {}
    if offline_access:
        data["offline_access"] = "on"
    if omit_claims:
        data["omit_claims"] = "on"
    else:
        data["claims_json"] = json.dumps(request_claims)
    response = session.post(
        f"{CLIENT}/login",
        data=data,
        allow_redirects=False,
        timeout=15,
    )
    check(response.is_redirect, f"Test-client /login did not redirect (HTTP {response.status_code}).")

    submitted: list[str] = []
    transitions: list[str] = []
    for _ in range(16):
        allow_loopback_secure_cookies(session)
        transitions.append(f"{response.status_code} {response.url}")
        if response.is_redirect:
            location = response.headers.get("Location")
            check(location is not None, "Redirect response did not include Location.")
            response = session.get(urljoin(response.url, location), allow_redirects=False, timeout=15)
            continue

        forms = parse_forms(response.text)
        if "kc-form-login" in forms:
            login_form = forms["kc-form-login"]
            # The lab flow identifies the user with a Username Form before
            # presenting the password form. Count only the credential-bearing
            # screen so existing assertions describe authentication methods,
            # not the identity bootstrap step.
            if "password" in login_form.values:
                submitted.append("kc-form-login")
                values = {"username": ALICE, "password": PASSWORD}
            else:
                values = {"username": ALICE}
            response = post_form(session, response, login_form, values)
            continue
        if "kc-otp-login-form" in forms:
            submitted.append("kc-otp-login-form")
            otp = smtp_verification_code(previous_smtp_messages) if use_email_code else current_totp()
            response = post_form(session, response, forms["kc-otp-login-form"], {"otp": otp})
            continue
        if "kc-totp-settings-form" in forms:
            raise CheckFailure("Keycloak asked to enrol OTP. The imported lab realm must provide Alice's fixed test TOTP credential.")

        # The Flask callback renders either the verified result or the public
        # authorization error as a terminal 200 response.
        if response.status_code == 200 and (
            "Verified authentication context" in response.text or 'class="error-page"' in response.text
        ):
            return AuthorizationResult(session, response, submitted)
        page_summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.text)).strip()[:240]
        raise CheckFailure(
            f"Unexpected page during authorization: HTTP {response.status_code} at {response.url}: {page_summary!r}; forms={list(forms)}."
        )

    raise CheckFailure("Authorization did not reach the test-client callback after 16 transitions: " + " -> ".join(transitions))


def detail_map(token: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details = token.get("amr_details")
    check(isinstance(details, list), "Token did not contain an amr_details array.")
    mapped: dict[str, dict[str, Any]] = {}
    for detail in details:
        check(isinstance(detail, dict), "amr_details contains a non-object execution.")
        identifier = detail.get("amr_identifier")
        check(isinstance(identifier, str), "An execution did not contain amr_identifier.")
        check(identifier not in mapped, f"Duplicate {identifier!r} execution in this lab event.")
        metadata = detail.get("amr_metadata")
        check(isinstance(metadata, dict) and isinstance(metadata.get("time"), str),
              f"{identifier!r} did not retain mandatory amr_metadata.time.")
        mapped[identifier] = detail
    return mapped


def detail_list(token: dict[str, Any]) -> list[dict[str, Any]]:
    """Return executions without collapsing repeated method identifiers."""
    details = token.get("amr_details")
    check(isinstance(details, list), "Token did not contain an amr_details array.")
    for detail in details:
        check(isinstance(detail, dict), "amr_details contains a non-object execution.")
        identifier = detail.get("amr_identifier")
        metadata = detail.get("amr_metadata")
        check(isinstance(identifier, str), "An execution did not contain amr_identifier.")
        check(isinstance(metadata, dict) and isinstance(metadata.get("time"), str),
              f"{identifier!r} did not retain mandatory amr_metadata.time.")
    return details


def assert_complete_event(id_token: dict[str, Any], userinfo: dict[str, Any], expected: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    id_details = detail_map(id_token)
    userinfo_details = detail_map(userinfo)
    check(set(id_details) == expected, f"ID Token executions were {sorted(id_details)}, expected {sorted(expected)}.")
    check(set(userinfo_details) == expected, f"UserInfo executions were {sorted(userinfo_details)}, expected {sorted(expected)}.")
    amr = id_token.get("amr")
    check(isinstance(amr, list) and set(amr) == expected,
          f"Standard amr was {amr!r}, expected the complete execution identifiers {sorted(expected)}.")
    for identifier in expected:
        check(id_details[identifier]["amr_metadata"]["time"] == userinfo_details[identifier]["amr_metadata"]["time"],
              f"{identifier!r} was not delivered from the same immutable event snapshot.")
    return id_details, userinfo_details


def success_result(request_claims: dict[str, Any], expected_forms: list[str]) -> tuple[AuthorizationResult, dict[str, Any], dict[str, Any]]:
    result = authorize(request_claims).require_success()
    check(result.forms == expected_forms, f"Authentication screens were {result.forms}, expected {expected_forms}.")
    return result, result.json_section("Verified ID Token"), result.json_section("Access-token-bound UserInfo")


def test_discovery_and_workbench() -> None:
    issuer_metadata = requests.get(f"{ISSUER}/.well-known/openid-configuration", timeout=15)
    check(issuer_metadata.status_code == 200,
          f"Issuer discovery returned HTTP {issuer_metadata.status_code}.")
    issuer_document = issuer_metadata.json()
    check("amr_details" in issuer_document.get("claims_supported", []),
          "Enabled discovery did not advertise the amr_details claim.")
    check(issuer_document.get("amr_details_request_supported") is True,
          "Enabled discovery did not advertise request-mode support.")
    check(issuer_document.get("pwd_metadata_supported") == ["iss", "location"],
          "Discovery did not advertise the native password metadata vocabulary.")
    check(issuer_document.get("location_types_supported") == ["ip_address"],
          "Discovery did not advertise the structured location type.")

    discovery = requests.get(f"{CLIENT}/discovery", timeout=15)
    check(discovery.status_code == 200, f"Test-client discovery endpoint returned HTTP {discovery.status_code}.")
    metadata = discovery.json()
    check(metadata.get("identifiers") == ["email", "otp", "pop", "pwd"], "Discovery did not expose the native method identifiers.")
    check("email_verification_method" in metadata["methods"]["email"]["properties"],
          "The visual builder did not receive the email property suggestion.")
    check("pwd_derivation_algorithm" in metadata["methods"]["pwd"]["properties"],
          "The visual builder did not receive the password property suggestion.")
    check("otp_algorithm" in metadata["methods"]["otp"]["properties"],
          "The visual builder did not receive the OTP property suggestion.")

    preview = requests.post(f"{CLIENT}/preview", data={"claims_json": json.dumps(claims(method("pwd")))}, timeout=15)
    check(preview.status_code == 200 and "amr_details" in preview.text,
          "The test-client workbench could not preview a valid request.")


def test_realm_switch_gates_discovery_and_authorization() -> None:
    """The realm switch disables both request mode and informational disclosure."""
    base = ISSUER.split("/realms/", 1)[0]
    headers = {"Authorization": f"Bearer {admin_token()}", "Content-Type": "application/json"}
    endpoint = f"{base}/admin/realms/oidc4ac"
    current = requests.get(endpoint, headers=headers, timeout=15)
    check(current.status_code == 200, f"Realm admin API returned HTTP {current.status_code}.")
    original = current.json()
    original_attributes = dict(original.get("attributes") or {})
    disabled = dict(original)
    disabled_attributes = dict(original_attributes)
    disabled_attributes["oidc4ac.enabled"] = "false"
    disabled["attributes"] = disabled_attributes
    update = requests.put(endpoint, headers=headers, json=disabled, timeout=15)
    check(update.status_code in {200, 204}, f"Could not disable OIDC4AC for the realm: HTTP {update.status_code}.")
    try:
        discovery = requests.get(f"{ISSUER}/.well-known/openid-configuration", timeout=15)
        check(discovery.status_code == 200, f"Disabled realm discovery returned HTTP {discovery.status_code}.")
        document = discovery.json()
        check("amr_details" not in document.get("claims_supported", []),
              "A disabled realm still advertised amr_details.")
        check("amr_identifiers_supported" not in document,
              "A disabled realm still advertised authentication-method capabilities.")

        result = authorize(claims(method("pwd"))).require_success()
        check("amr_details" not in result.json_section("Verified ID Token"),
              "A disabled realm emitted amr_details in the ID Token.")
        check("amr_details" not in result.json_section("Access-token-bound UserInfo"),
              "A disabled realm emitted amr_details in UserInfo.")
    finally:
        restored = requests.get(endpoint, headers=headers, timeout=15)
        check(restored.status_code == 200, f"Could not reload the realm for restoration: HTTP {restored.status_code}.")
        restored_realm = restored.json()
        restored_realm["attributes"] = original_attributes
        restore = requests.put(endpoint, headers=headers, json=restored_realm, timeout=15)
        check(restore.status_code in {200, 204}, f"Could not restore OIDC4AC realm setting: HTTP {restore.status_code}.")


def test_optional_metadata_uses_protocol_location_object() -> None:
    request = {
        "id_token": {"amr_details": {
            "essential": True,
            **method("pwd"),
            "amr_metadata": {
                "time": {"essential": True},
                "iss": None,
                "location": None,
            },
        }},
        "userinfo": {"amr_details": {
            "essential": True,
            **method("pwd"),
            "amr_metadata": {
                "time": {"essential": True},
                "iss": None,
                "location": None,
            },
        }},
    }
    result = authorize(request).require_success()
    id_details, userinfo_details = assert_complete_event(
        result.json_section("Verified ID Token"),
        result.json_section("Access-token-bound UserInfo"),
        {"pwd"},
    )
    for label, details in (("ID Token", id_details), ("UserInfo", userinfo_details)):
        metadata = details["pwd"]["amr_metadata"]
        check(metadata.get("iss") == ISSUER, f"{label} did not preserve the realm issuer metadata.")
        location = metadata.get("location")
        check(isinstance(location, dict), f"{label} location metadata was not a JSON object.")
        check(isinstance(location.get("ip_address"), str) and location["ip_address"],
              f"{label} location metadata did not contain an IP address.")
        check(not isinstance(location, str), f"{label} used the legacy scalar location representation.")


def test_client_and_redirect_validation_precedes_authentication() -> None:
    common = {
        "response_type": "code",
        "redirect_uri": f"{CLIENT}/callback",
        "scope": "openid",
        "state": "endpoint-validation-state",
        "nonce": "endpoint-validation-nonce",
        "claims": json.dumps(claims(method("pwd")), separators=(",", ":")),
    }
    invalid_client = requests.get(f"{ISSUER}/protocol/openid-connect/auth",
                                  params={**common, "client_id": "not-a-registered-client"},
                                  allow_redirects=False, timeout=15)
    check(invalid_client.status_code == 400, f"Invalid client request returned HTTP {invalid_client.status_code}.")
    check(not invalid_client.is_redirect, "Invalid client validation unexpectedly redirected.")
    check("invalid_request" not in invalid_client.headers.get("Location", ""),
          "Invalid client validation exposed a redirect target.")

    invalid_redirect = requests.get(f"{ISSUER}/protocol/openid-connect/auth",
                                    params={**common, "client_id": "oidc4ac-test-client",
                                            "redirect_uri": "http://localhost:5999/not-registered"},
                                    allow_redirects=False, timeout=15)
    check(invalid_redirect.status_code == 400,
          f"Invalid redirect URI returned HTTP {invalid_redirect.status_code}.")
    check(not invalid_redirect.is_redirect, "Invalid redirect URI unexpectedly redirected.")
    check("unmet_authentication_requirements" not in invalid_redirect.text,
          "Redirect validation reached the OIDC4AC authentication error bridge.")


def test_admin_api_exposes_configured_factor_container() -> None:
    base = ISSUER.split("/realms/", 1)[0]
    headers = {"Authorization": f"Bearer {admin_token()}"}
    response = requests.get(f"{base}/admin/realms/oidc4ac/authentication/flows/oidc4ac%20browser%20forms/executions",
                            headers=headers, timeout=15)
    check(response.status_code == 200, f"Authentication-flow admin API returned HTTP {response.status_code}.")
    executions = response.json()
    planner = next((execution for execution in executions if execution.get("providerId") == "oidc4ac-factor-planner"), None)
    check(planner is not None, "The configured browser flow did not expose the OIDC4AC factor planner to the admin API.")
    config_id = planner.get("authenticationConfig")
    check(isinstance(config_id, str) and config_id, "The factor planner execution did not expose its configuration id.")
    config_response = requests.get(f"{base}/admin/realms/oidc4ac/authentication/config/{quote(config_id, safe='')}",
                                   headers=headers, timeout=15)
    check(config_response.status_code == 200,
          f"Factor planner configuration endpoint returned HTTP {config_response.status_code}.")
    config = config_response.json().get("config") or {}
    check(config.get("factor_flow_alias") == "oidc4ac-factors",
          "The planner's factor-flow configuration was not visible through the Authentication tab API.")
    factor_flow_names = {execution.get("displayName") for execution in executions}
    check("oidc4ac-factors" in factor_flow_names,
          "The configured OIDC4AC factor container was not visible through the admin API.")


def test_realm_and_client_disclosure_policy_is_enforced() -> None:
    base = ISSUER.split("/realms/", 1)[0]
    headers = {"Authorization": f"Bearer {admin_token()}", "Content-Type": "application/json"}
    endpoint = f"{base}/admin/realms/oidc4ac/ui-ext/oidc4ac"
    payload = {
        "clientId": "oidc4ac-test-client",
        "realmDisclosureModes": {
            "amr_properties.pwd_derivation_algorithm": "never",
        },
        "realmPolicyUpdate": True,
        "clientPolicyUpdate": False,
    }
    response = requests.put(endpoint, headers=headers, json=payload, timeout=15)
    check(response.status_code == 200, f"OIDC4AC disclosure configuration returned HTTP {response.status_code}: {response.text[:240]}")
    try:
        denied = authorize(claims(method("pwd", properties={"pwd_derivation_algorithm": {"essential": True}})))
        denied.require_error("unmet_authentication_requirements")

        payload["realmDisclosureModes"] = {
            "amr_metadata.iss": "never",
        }
        response = requests.put(endpoint, headers=headers, json=payload, timeout=15)
        check(response.status_code == 200, f"Metadata disclosure configuration returned HTTP {response.status_code}.")
        essential_issuer = {
            "id_token": {"amr_details": {
                "essential": True,
                **method("pwd"),
                "amr_metadata": {
                    "time": {"essential": True},
                    "iss": {"essential": True},
                },
            }},
        }
        issuer_denied = authorize(essential_issuer).require_error("unmet_authentication_requirements")
        check(ISSUER not in issuer_denied.response.text,
              "The denied issuer metadata appeared in the public essential-failure response.")

        payload["realmDisclosureModes"] = {
            "amr_properties.pwd_derivation_algorithm": "never",
        }

        preferred = authorize(claims(method("pwd"))).require_success()
        id_token = preferred.json_section("Verified ID Token")
        detail = detail_map(id_token)["pwd"]
        check("amr_properties" not in detail,
              "A non-essential property denied by the disclosure policy was emitted.")

        payload["realmDisclosureModes"] = {
            "amr_properties.pwd_derivation_algorithm": "requested",
        }
        response = requests.put(endpoint, headers=headers, json=payload, timeout=15)
        check(response.status_code == 200, f"Requested-only realm disclosure configuration returned HTTP {response.status_code}.")
        null_request = authorize({"id_token": {"amr_details": None}}).require_success()
        null_detail = detail_map(null_request.json_section("Verified ID Token"))["pwd"]
        check("amr_properties" not in null_detail,
              "A requested-only property was disclosed without a field-specific request.")
        explicit_request = authorize(claims(method("pwd", properties={"pwd_derivation_algorithm": None}))).require_success()
        explicit_detail = detail_map(explicit_request.json_section("Verified ID Token"))["pwd"]
        check("pwd_derivation_algorithm" in explicit_detail.get("amr_properties", {}),
              "A requested-only property was not disclosed when explicitly requested.")

        payload["realmDisclosureModes"] = {}
        payload["clientDisclosureModes"] = {
            "amr_properties.pwd_derivation_algorithm": "never",
        }
        payload["clientPolicyUpdate"] = True
        response = requests.put(endpoint, headers=headers, json=payload, timeout=15)
        check(response.status_code == 200, f"Client disclosure configuration returned HTTP {response.status_code}.")
        denied_by_client = authorize(claims(method("pwd", properties={"pwd_derivation_algorithm": {"essential": True}})))
        denied_by_client.require_error("unmet_authentication_requirements")
    finally:
        payload["realmDisclosureModes"] = {}
        payload["clientDisclosureModes"] = {}
        payload["clientPolicyUpdate"] = True
        requests.put(endpoint, headers=headers, json=payload, timeout=15)


def test_unmet_error_response_modes() -> None:
    common = {
        "response_type": "code",
        "client_id": "oidc4ac-test-client",
        "redirect_uri": f"{CLIENT}/callback",
        "scope": "openid",
        "state": "response-mode-state",
        "nonce": "response-mode-nonce",
        "claims": json.dumps(claims(method("face")), separators=(",", ":")),
    }
    for response_mode in ("query", "fragment", "form_post"):
        response = direct_authorization({**common, "response_mode": response_mode})
        if response_mode == "form_post":
            values = parse_first_form(response.text).values
            check(values.get("error") == "unmet_authentication_requirements",
                  "form_post did not carry the generic OIDC4AC error.")
            check(values.get("state") == common["state"],
                  "form_post did not preserve the request state.")
        else:
            location = response.headers.get("Location")
            check(location is not None, f"{response_mode} error response did not include a redirect location.")
            parsed = urlparse(location)
            values = parse_qs(parsed.query if response_mode == "query" else parsed.fragment)
            check(values.get("error") == ["unmet_authentication_requirements"],
                  f"{response_mode} did not carry the generic OIDC4AC error.")
            check(values.get("state") == [common["state"]],
                  f"{response_mode} did not preserve the request state.")


def test_unmet_error_jarm_response_mode() -> None:
    common = {
        "response_type": "code",
        "client_id": "oidc4ac-test-client",
        "redirect_uri": f"{CLIENT}/callback",
        "scope": "openid",
        "state": "jarm-response-mode-state",
        "nonce": "jarm-response-mode-nonce",
        "response_mode": "jwt",
        "claims": json.dumps(claims(method("face")), separators=(",", ":")),
    }
    response = direct_authorization(common)
    location = response.headers.get("Location")
    check(location is not None, "JARM error response did not include a redirect location.")
    parsed = urlparse(location)
    values = parse_qs(parsed.query or parsed.fragment)
    encoded = values.get("response", [None])[0]
    check(encoded is not None, "JARM redirect did not carry a response JWT.")
    payload = decode_unverified_jwt_payload(encoded)
    check(payload.get("error") == "unmet_authentication_requirements",
          f"JARM did not carry the generic OIDC4AC error: {payload!r}.")
    check(payload.get("state") == common["state"], "JARM did not preserve the request state.")


def test_concurrent_grants_keep_location_projections_isolated() -> None:
    requests_by_location = [
        claims(method("pwd"), id_token=True, userinfo=False),
        claims(method("pwd"), id_token=False, userinfo=True),
    ]
    seed = authorize(claims(method("pwd"))).require_success()
    sessions = []
    for _ in requests_by_location:
        session = requests.Session()
        session.cookies.update(seed.session.cookies)
        sessions.append(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda arguments: authorize(arguments[0], session=arguments[1], prompt_login=False),
            zip(requests_by_location, sessions),
        ))

    id_only, userinfo_only = results
    id_only_token = id_only.require_success().json_section("Verified ID Token")
    id_only_userinfo = id_only.json_section("Access-token-bound UserInfo")
    userinfo_only_token = userinfo_only.require_success().json_section("Verified ID Token")
    userinfo_only_userinfo = userinfo_only.json_section("Access-token-bound UserInfo")
    check(detail_map(id_only_token)["pwd"]["amr_identifier"] == "pwd",
          "The concurrent ID Token-only grant lost its requested projection.")
    check("amr_details" not in id_only_userinfo,
          "The concurrent ID Token-only grant leaked amr_details into UserInfo.")
    check("amr_details" not in userinfo_only_token,
          "The concurrent UserInfo-only grant leaked amr_details into its ID Token.")
    check(detail_map(userinfo_only_userinfo)["pwd"]["amr_identifier"] == "pwd",
          "The concurrent UserInfo-only grant lost its requested projection.")
    id_time = detail_map(id_only_token)["pwd"]["amr_metadata"]["time"]
    userinfo_time = detail_map(userinfo_only_userinfo)["pwd"]["amr_metadata"]["time"]
    check(id_time == userinfo_time, "Concurrent SSO grants did not reuse the same authentication-event time.")

    for result, id_token_expected, userinfo_expected in ((id_only, True, False), (userinfo_only, False, True)):
        refreshed = result.session.post(f"{CLIENT}/refresh", allow_redirects=True, timeout=15)
        refresh_result = AuthorizationResult(result.session, refreshed, []).require_success()
        refreshed_id = refresh_result.json_section("Verified ID Token")
        refreshed_userinfo = refresh_result.json_section("Access-token-bound UserInfo")
        check(("amr_details" in refreshed_id) is id_token_expected,
              "Concurrent refresh changed the ID Token disclosure projection.")
        check(("amr_details" in refreshed_userinfo) is userinfo_expected,
              "Concurrent refresh changed the UserInfo disclosure projection.")


def test_essential_password_and_refresh() -> None:
    request_claims = claims(method("pwd", properties={"pwd_derivation_algorithm": None}, max_age=300))
    result, id_token, userinfo = success_result(request_claims, ["kc-form-login"])
    id_details, userinfo_details = assert_complete_event(id_token, userinfo, {"pwd"})
    check("pwd_derivation_algorithm" in id_details["pwd"].get("amr_properties", {}),
          "Requested password property was absent from the ID Token projection.")
    check("pwd_derivation_algorithm" in userinfo_details["pwd"].get("amr_properties", {}),
          "Requested password property was absent from the UserInfo projection.")

    for attempt in (1, 2):
        refreshed = result.session.post(f"{CLIENT}/refresh", allow_redirects=True, timeout=15)
        refresh_result = AuthorizationResult(result.session, refreshed, [])
        refresh_result.require_success()
        check("Refresh token response" in refreshed.text,
              f"The test client did not render refresh attempt {attempt}.")
        refreshed_id = refresh_result.json_section("Verified ID Token")
        refreshed_userinfo = refresh_result.json_section("Access-token-bound UserInfo")
        check(detail_map(refreshed_id) == id_details,
              f"Refresh-derived ID Token attempt {attempt} did not reuse the authorization event snapshot.")
        check(detail_map(refreshed_userinfo) == userinfo_details,
              f"Refresh-derived UserInfo attempt {attempt} did not reuse the authorization event snapshot.")


def test_password_credential_metadata_is_projected() -> None:
    """Credential-derived password metadata is exposed only when requested."""
    requested = claims(method("pwd", properties={
        "pwd_derivation_algorithm": None,
        "pwd_iterations": None,
        "pwd_last_updated_at": None,
    }))
    result, id_token, userinfo = success_result(requested, ["kc-form-login"])
    id_details, userinfo_details = assert_complete_event(id_token, userinfo, {"pwd"})

    for label, details in (("ID Token", id_details), ("UserInfo", userinfo_details)):
        properties = details["pwd"].get("amr_properties")
        check(isinstance(properties, dict), f"{label} omitted requested password credential metadata.")
        check(isinstance(properties.get("pwd_derivation_algorithm"), str)
              and properties["pwd_derivation_algorithm"],
              f"{label} did not expose the password derivation algorithm.")
        check(isinstance(properties.get("pwd_iterations"), int)
              and properties["pwd_iterations"] > 0,
              f"{label} did not expose a positive password iteration count.")
        updated_at = properties.get("pwd_last_updated_at")
        check(isinstance(updated_at, str) and updated_at.endswith("Z"),
              f"{label} did not expose an RFC 3339 password update timestamp.")

    check(id_details["pwd"]["amr_properties"] == userinfo_details["pwd"]["amr_properties"],
          "ID Token and UserInfo projected different password credential metadata from one event.")


def test_access_token_does_not_contain_amr_details() -> None:
    result = authorize(claims(method("pwd"))).require_success()
    access_token = result.json_section("Verified Access Token (claims only)")
    check(isinstance(access_token.get("sub"), str),
          "The test client could not decode the verified access-token payload.")
    check("amr_details" not in access_token,
          "OIDC4AC amr_details leaked into the access token.")


def test_null_claim_requests_complete_event_without_method_requirement() -> None:
    request = {
        "id_token": {"amr_details": None},
        "userinfo": {"amr_details": None},
    }
    result = authorize(request).require_success()
    id_token = result.json_section("Verified ID Token")
    userinfo = result.json_section("Access-token-bound UserInfo")
    id_details, userinfo_details = assert_complete_event(id_token, userinfo, {"pwd"})
    check("amr_properties" in id_details["pwd"],
          "A null claim request did not return available password properties.")
    check("amr_properties" in userinfo_details["pwd"],
          "A null claim request did not return available UserInfo properties.")


def test_essential_claim_without_expression_requests_complete_event() -> None:
    """Claim-level essentiality requires a conforming claim, not a factor."""
    request = {
        "id_token": {"amr_details": {"essential": True}},
        "userinfo": {"amr_details": {"essential": True}},
    }
    result = authorize(request).require_success()
    id_details, userinfo_details = assert_complete_event(
        result.json_section("Verified ID Token"),
        result.json_section("Access-token-bound UserInfo"),
        {"pwd"},
    )
    check(id_details["pwd"]["amr_metadata"].get("time"),
          "An essential claim without an expression omitted the mandatory execution time.")
    check(userinfo_details["pwd"]["amr_metadata"].get("time") == id_details["pwd"]["amr_metadata"].get("time"),
          "ID Token and UserInfo did not use the same event for an expression-free essential claim.")


def test_best_effort_value_constraint_reports_actual_property() -> None:
    # The local value constraint is deliberately not essential. Keycloak must
    # attempt it, but it must not synthesize the requested value or fail the
    # authorization when the verified credential has a different value.
    request = claims(method("pwd", properties={
        "pwd_derivation_algorithm": {"value": "not-the-lab-algorithm"},
    }))
    result = authorize(request).require_success()
    details = detail_map(result.json_section("Verified ID Token"))
    actual = details["pwd"].get("amr_properties", {}).get("pwd_derivation_algorithm")
    check(actual is not None and actual != "not-the-lab-algorithm",
          "The best-effort password constraint was copied into the event instead of reporting the actual value.")


def test_identifier_values_and_numeric_property_bounds() -> None:
    identifier_values = {
        "id_token": {"amr_details": {
            "essential": True,
            "amr_identifier": {"values": ["otp", "pwd"]},
            "amr_metadata": {"time": {"essential": True}},
        }},
    }
    identifier_result = authorize(identifier_values).require_success()
    identifier_details = detail_map(identifier_result.json_section("Verified ID Token"))
    check(set(identifier_details) == {"pwd"},
          f"An identifier values constraint did not select the realm-priority password path: {identifier_details!r}.")

    bounded = claims(method("otp", properties={
        "otp_algorithm": {"essential": True, "values": ["TOTP", "HOTP"]},
        "otp_length": {"essential": True, "min": 6, "max": 6},
        "otp_time_to_live": {"essential": True, "min": 30, "max": 30},
    }))
    bounded_result = authorize(bounded).require_success()
    otp_details = detail_map(bounded_result.json_section("Verified ID Token"))["otp"]
    properties = otp_details.get("amr_properties", {})
    check(properties.get("otp_algorithm") == "TOTP", "OTP values constraint did not match the verified algorithm.")
    check(properties.get("otp_length") == 6, "OTP minimum/maximum length constraints were not evaluated.")
    check(properties.get("otp_time_to_live") == 30, "OTP numeric lifetime constraints were not evaluated.")


def test_oidc4ac_sso_reuse_preserves_original_execution_time() -> None:
    first = authorize(claims(method("pwd"))).require_success()
    first_id = detail_map(first.json_section("Verified ID Token"))
    second = authorize(claims(method("pwd")), session=first.session, prompt_login=False).require_success()
    check(second.forms == [], f"A satisfied OIDC4AC SSO request unexpectedly reauthenticated: {second.forms!r}.")
    second_id = detail_map(second.json_section("Verified ID Token"))
    check(second_id["pwd"]["amr_metadata"]["time"] == first_id["pwd"]["amr_metadata"]["time"],
          "OIDC4AC SSO reuse changed the original password execution time.")
    second_userinfo = detail_map(second.json_section("Access-token-bound UserInfo"))
    check(second_userinfo["pwd"]["amr_metadata"]["time"] == first_id["pwd"]["amr_metadata"]["time"],
          "OIDC4AC SSO UserInfo did not reuse the original execution time.")


def test_offline_refresh_reuses_the_same_snapshot() -> None:
    result = authorize(claims(method("pwd")), offline_access=True).require_success()
    original = detail_list(result.json_section("Verified ID Token"))
    access_token = result.json_section("Verified Access Token (claims only)")
    check("offline_access" in str(access_token.get("scope", "")),
          "The offline-access request did not receive the requested offline scope.")

    # The RP no longer needs the browser SSO cookie to redeem this grant. This
    # exercises the offline refresh path while preserving the server-side
    # immutable event snapshot.
    clear_keycloak_cookies(result.session)
    refreshed = result.session.post(f"{CLIENT}/refresh", allow_redirects=True, timeout=15)
    refresh_result = AuthorizationResult(result.session, refreshed, []).require_success()
    check(detail_list(refresh_result.json_section("Verified ID Token")) == original,
          "Offline refresh reconstructed or changed the authentication event.")
    check("amr_details" not in refresh_result.json_section("Verified Access Token (claims only)"),
          "Offline refresh leaked amr_details into the access token.")


def test_old_grant_userinfo_survives_a_later_authentication() -> None:
    first = authorize(claims(method("pwd"))).require_success()
    first_details = detail_list(first.json_section("Verified ID Token"))
    first_cookies = first.session.cookies.copy()

    later_session = requests.Session()
    later_session.cookies.update(first_cookies)
    stronger = authorize(
        claims({"all_of": [method("pwd"), method("otp")]}, id_token=True, userinfo=True),
        session=later_session,
        prompt_login=False,
    ).require_success()
    check([detail["amr_identifier"] for detail in detail_list(stronger.json_section("Verified ID Token"))]
          == ["pwd", "otp"],
          "The later authentication did not record the stronger authentication event.")

    # The original grant must remain tied to its own immutable snapshot even
    # after the user session has recorded a newer event.
    old_refresh = first.session.post(f"{CLIENT}/refresh", allow_redirects=True, timeout=15)
    old_result = AuthorizationResult(first.session, old_refresh, []).require_success()
    check(detail_list(old_result.json_section("Verified ID Token")) == first_details,
          "A later login changed the older grant's refresh snapshot.")
    check(detail_list(old_result.json_section("Access-token-bound UserInfo")) == first_details,
          "Later UserInfo was reconstructed from mutable session state.")


def test_ordinary_oidc_login_without_claims_parameter() -> None:
    result = authorize({}, omit_claims=True).require_success()
    check(result.forms == ["kc-form-login"], "An ordinary OIDC login did not use the normal password form.")
    id_token = result.json_section("Verified ID Token")
    userinfo = result.json_section("Access-token-bound UserInfo")
    check("amr_details" not in id_token and "amr_details" not in userinfo,
          "A request without a claims parameter unexpectedly received amr_details.")


def test_best_effort_unsupported_method_does_not_block_login() -> None:
    result = authorize(claims(method("face"), essential=False)).require_success()
    check(result.forms == ["kc-form-login"], "A best-effort unsupported method did not fall back to normal login.")
    id_token = result.json_section("Verified ID Token")
    userinfo = result.json_section("Access-token-bound UserInfo")
    check("face" not in json.dumps(id_token) and "face" not in json.dumps(userinfo),
          "A best-effort unsupported method was presented as if it had executed.")


def test_single_location_disclosure() -> None:
    id_only_result = authorize(claims(method("pwd"), userinfo=False)).require_success()
    id_only = id_only_result.json_section("Verified ID Token")
    id_only_userinfo = id_only_result.json_section("Access-token-bound UserInfo")
    check(detail_map(id_only)["pwd"]["amr_identifier"] == "pwd",
          "The ID Token-only request did not preserve the requested password execution.")
    check("amr_details" not in id_only_userinfo, "UserInfo received a claim that was not requested there.")

    userinfo_only_result = authorize(claims(method("pwd"), id_token=False)).require_success()
    userinfo_only = userinfo_only_result.json_section("Verified ID Token")
    userinfo_only_userinfo = userinfo_only_result.json_section("Access-token-bound UserInfo")
    check("amr_details" not in userinfo_only, "The ID Token received a claim that was not requested there.")
    check(detail_map(userinfo_only_userinfo)["pwd"]["amr_identifier"] == "pwd",
          "The UserInfo-only request did not preserve the requested password execution.")


def test_malformed_logical_expression_is_rejected() -> None:
    malformed = {
        "id_token": {
            "amr_details": {
                "essential": True,
                "all_of": [],
            }
        }
    }
    result = authorize(malformed).require_error("invalid_request")
    check(result.forms == [], "Malformed logical grammar reached an authentication form.")


def test_ordinary_sso_reuse_without_oidc4ac_claim() -> None:
    first = authorize({}, omit_claims=True).require_success()
    second = authorize({}, session=first.session, prompt_login=False, omit_claims=True).require_success()
    check(second.forms == [], "SSO reuse unexpectedly displayed an authentication form.")
    second_id = second.json_section("Verified ID Token")
    second_userinfo = second.json_section("Access-token-bound UserInfo")
    check("amr_details" not in second_id and "amr_details" not in second_userinfo,
          "Ordinary SSO reuse unexpectedly produced an OIDC4AC claim.")


def test_sso_reauthentication_for_stronger_request() -> None:
    """A stronger request re-runs the configured browser flow and satisfies both factors."""
    first = authorize(claims(method("pwd"))).require_success()
    stronger = claims({"all_of": [method("pwd"), method("otp")]})
    second = authorize(stronger, session=first.session, prompt_login=False).require_success()
    check(second.forms == ["kc-form-login", "kc-otp-login-form"],
          f"A stronger SSO request did not re-run the configured factor flow: {second.forms!r}.")
    second_id, second_userinfo = assert_complete_event(
        second.json_section("Verified ID Token"),
        second.json_section("Access-token-bound UserInfo"),
        {"pwd", "otp"},
    )
    check(second_id["pwd"]["amr_metadata"]["time"], "Reauthenticated password execution had no timestamp.")
    check(second_userinfo["pwd"]["amr_metadata"]["time"] == second_id["pwd"]["amr_metadata"]["time"],
          "UserInfo did not reuse the reauthentication event timestamp.")


def test_max_age_forces_reauthentication() -> None:
    first = authorize(claims(method("pwd"))).require_success()
    # Use a short non-zero bound and cross it deliberately; max_age=0 is
    # covered at unit level because a browser round-trip can cross a second
    # boundary while the user is entering credentials.
    time.sleep(2)
    second = authorize(claims(method("pwd", max_age=1)), session=first.session, prompt_login=False).require_success()
    check(second.forms == ["kc-form-login"],
          "An essential max_age=1 request reused a stale password SSO event.")


def test_best_effort_leaf_inside_all_of_does_not_block() -> None:
    expression = {"all_of": [method("pwd"), method("face")]}
    result, id_token, userinfo = success_result(claims(expression, essential=False), ["kc-form-login"])
    id_details, userinfo_details = assert_complete_event(id_token, userinfo, {"pwd"})
    check("face" not in json.dumps(id_details) and "face" not in json.dumps(userinfo_details),
          "A best-effort unsupported all_of leaf appeared in the event.")


def test_invalid_method_shape_is_rejected_before_authentication() -> None:
    invalid = {
        "id_token": {
            "amr_details": {
                "essential": True,
                "amr_identifier": {"value": "pwd"},
                "amr_metadata": {},
            }
        }
    }
    result = authorize(invalid).require_error("invalid_request")
    check(result.forms == [], "An invalid method object reached an authentication form.")


def test_invalid_request_grammar_variants_are_rejected_before_authentication() -> None:
    invalid_requests = [
        {
            "id_token": {"amr_details": {"essential": True, "unknown_operator": []}},
        },
        {
            "id_token": {"amr_details": {"essential": True, "all_of": [
                {"essential": True, **method("pwd")},
            ]}},
        },
        {
            "id_token": {"amr_details": {"essential": True, **method("pwd", properties={
                "pwd_iterations": {"value": 1, "values": [1]},
            })}},
        },
        {
            "id_token": {"amr_details": {"essential": True, **method("pwd", properties={
                "pwd_iterations": {"max_age": 1},
            })}},
        },
    ]
    for index, invalid in enumerate(invalid_requests, start=1):
        result = authorize(invalid).require_error("invalid_request")
        check(result.forms == [], f"Invalid grammar variant {index} reached an authentication form.")


def test_password_and_otp_all_of() -> None:
    expression = {"all_of": [method("pwd"), method("otp", properties={"otp_algorithm": {"value": "TOTP", "essential": True}})]}
    _, id_token, userinfo = success_result(claims(expression), ["kc-form-login", "kc-otp-login-form"])
    id_details, userinfo_details = assert_complete_event(id_token, userinfo, {"pwd", "otp"})
    check(id_details["otp"].get("amr_properties", {}).get("otp_algorithm") == "TOTP",
          "OTP properties did not describe the verified TOTP credential in the ID Token.")
    check(userinfo_details["otp"].get("amr_properties", {}).get("otp_algorithm") == "TOTP",
          "OTP properties did not describe the verified TOTP credential in UserInfo.")


def test_email_authenticator_sends_and_verifies_code() -> None:
    expression = method("email", properties={
        "email_verification_method": {"value": "code", "essential": True},
    })
    result = authorize(claims(expression), use_email_code=True).require_success()
    check(result.forms == ["kc-otp-login-form"],
          f"Email authentication did not use the standard verification-code form: {result.forms!r}.")
    id_details, userinfo_details = assert_complete_event(
        result.json_section("Verified ID Token"),
        result.json_section("Access-token-bound UserInfo"),
        {"email"},
    )
    for label, details in (("ID Token", id_details), ("UserInfo", userinfo_details)):
        properties = details["email"].get("amr_properties", {})
        check(properties.get("email_verification_method") == "code",
              f"{label} did not preserve the email verification-method property.")


def test_repeated_method_executions_preserve_each_timestamp() -> None:
    expression = {"all_of": [method("pwd"), method("pwd")]}
    result = authorize(claims(expression)).require_success()
    check(result.forms == ["kc-form-login", "kc-form-login"],
          f"Repeated password execution did not run twice: {result.forms!r}.")
    id_details = detail_list(result.json_section("Verified ID Token"))
    userinfo_details = detail_list(result.json_section("Access-token-bound UserInfo"))
    check([detail["amr_identifier"] for detail in id_details] == ["pwd", "pwd"],
          "The complete event omitted one repeated password execution.")
    check([detail["amr_metadata"]["time"] for detail in id_details]
          == [detail["amr_metadata"]["time"] for detail in userinfo_details],
          "ID Token and UserInfo did not preserve repeated execution timestamps.")


def test_independent_delivery_projections_preserve_the_complete_event() -> None:
    request_claims = {
        "id_token": {"amr_details": {"essential": True, **method("pwd", properties={"pwd_derivation_algorithm": None})}},
        "userinfo": {"amr_details": {"essential": True, **method("otp", properties={"otp_algorithm": {"value": "TOTP", "essential": True}})}},
    }
    _, id_token, userinfo = success_result(request_claims, ["kc-form-login", "kc-otp-login-form"])
    id_details, userinfo_details = assert_complete_event(id_token, userinfo, {"pwd", "otp"})
    check("pwd_derivation_algorithm" in id_details["pwd"].get("amr_properties", {}),
          "ID Token omitted the password property it requested.")
    check("amr_properties" not in id_details["otp"],
          "ID Token disclosed an unrequested OTP property.")
    check("otp_algorithm" in userinfo_details["otp"].get("amr_properties", {}),
          "UserInfo omitted the OTP property it requested.")
    check("amr_properties" not in userinfo_details["pwd"],
          "UserInfo disclosed an unrequested password property.")


def test_one_of_uses_realm_priority() -> None:
    expression = {"one_of": [method("pwd"), method("otp")]}
    _, id_token, userinfo = success_result(claims(expression), ["kc-form-login"])
    assert_complete_event(id_token, userinfo, {"pwd"})


def test_nested_expression_selects_the_preferred_satisfiable_branch() -> None:
    expression = {"one_of": [{"all_of": [method("pwd"), method("otp")]}, method("pop")]}
    _, id_token, userinfo = success_result(claims(expression), ["kc-form-login", "kc-otp-login-form"])
    assert_complete_event(id_token, userinfo, {"pwd", "otp"})


def test_essential_constraint_failure_is_generic() -> None:
    impossible = method("pwd", properties={"pwd_derivation_algorithm": {"value": "not-a-real-derivation", "essential": True}})
    result = authorize(claims(impossible)).require_error("unmet_authentication_requirements")
    check(result.forms == ["kc-form-login"], "A supported password request should reach the password screen before its property fails.")
    check("not-a-real-derivation" not in result.response.text,
          "The public error leaked an essential property constraint value.")


def test_unsupported_essential_method_is_generic() -> None:
    result = authorize(claims(method("face"))).require_error("unmet_authentication_requirements")
    check(result.forms == [], "An unplannable essential method should fail before displaying an unrelated factor.")
    page = result.response.text.lower()
    check("enrol" not in page and "unsupported" not in page and "face" not in page,
          "The public error leaked method availability or enrolment information.")


def wait_for_lab() -> None:
    deadline = time.monotonic() + TIMEOUT
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{CLIENT}/healthz", timeout=3)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as error:
            last_error = str(error)
        time.sleep(1)
    raise CheckFailure(f"Test client at {CLIENT} did not become ready within {TIMEOUT:g}s ({last_error}).")


def main() -> int:
    wait_for_lab()
    cases: list[tuple[str, Callable[[], None]]] = [
        ("discovery and visual-workbench request handling", test_discovery_and_workbench),
        ("realm switch gates discovery and authorization", test_realm_switch_gates_discovery_and_authorization),
        ("structured optional metadata", test_optional_metadata_uses_protocol_location_object),
        ("client and redirect validation", test_client_and_redirect_validation_precedes_authentication),
        ("configured factor flow is visible to the admin API", test_admin_api_exposes_configured_factor_container),
        ("realm and client disclosure policy", test_realm_and_client_disclosure_policy_is_enforced),
        ("query, fragment, and form_post error modes", test_unmet_error_response_modes),
        ("JARM error response mode", test_unmet_error_jarm_response_mode),
        ("essential password, freshness, and refresh snapshot", test_essential_password_and_refresh),
        ("password credential metadata projection", test_password_credential_metadata_is_projected),
        ("access token excludes amr_details", test_access_token_does_not_contain_amr_details),
        ("null claim requests the complete event", test_null_claim_requests_complete_event_without_method_requirement),
        ("essential claim without expression", test_essential_claim_without_expression_requests_complete_event),
        ("offline refresh reuses the immutable snapshot", test_offline_refresh_reuses_the_same_snapshot),
        ("old grant survives a later authentication", test_old_grant_userinfo_survives_a_later_authentication),
        ("ordinary OIDC login without a claims parameter", test_ordinary_oidc_login_without_claims_parameter),
        ("best-effort unsupported method", test_best_effort_unsupported_method_does_not_block_login),
        ("best-effort value constraint reports actual property", test_best_effort_value_constraint_reports_actual_property),
        ("identifier values and numeric property bounds", test_identifier_values_and_numeric_property_bounds),
        ("essential password and OTP all_of", test_password_and_otp_all_of),
        ("email authenticator sends and verifies an SMTP code", test_email_authenticator_sends_and_verifies_code),
        ("repeated method executions preserve timestamps", test_repeated_method_executions_preserve_each_timestamp),
        ("independent delivery projections retain one complete event", test_independent_delivery_projections_preserve_the_complete_event),
        ("single-location disclosure", test_single_location_disclosure),
        ("one_of branch policy", test_one_of_uses_realm_priority),
        ("nested all_of / one_of branch policy", test_nested_expression_selects_the_preferred_satisfiable_branch),
        ("essential property constraint failure", test_essential_constraint_failure_is_generic),
        ("unsupported essential method failure", test_unsupported_essential_method_is_generic),
        ("malformed logical expression", test_malformed_logical_expression_is_rejected),
        ("SSO reauthentication for stronger request", test_sso_reauthentication_for_stronger_request),
        ("essential max_age forces reauthentication", test_max_age_forces_reauthentication),
        ("best-effort all_of leaf", test_best_effort_leaf_inside_all_of_does_not_block),
        ("invalid method shape", test_invalid_method_shape_is_rejected_before_authentication),
        ("invalid grammar variants", test_invalid_request_grammar_variants_are_rejected_before_authentication),
        ("ordinary SSO reuse without OIDC4AC claims", test_ordinary_sso_reuse_without_oidc4ac_claim),
        ("OIDC4AC SSO reuse preserves execution time", test_oidc4ac_sso_reuse_preserves_original_execution_time),
        ("concurrent grants retain isolated projections", test_concurrent_grants_keep_location_projections_isolated),
    ]
    print(f"OIDC4AC lab end-to-end suite against {CLIENT}")
    for name, case in cases:
        try:
            case()
        except Exception as error:
            print(f"FAIL  {name}: {error}", file=sys.stderr)
            return 1
        print(f"PASS  {name}")
    print(f"PASS  {len(cases)} end-to-end scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
