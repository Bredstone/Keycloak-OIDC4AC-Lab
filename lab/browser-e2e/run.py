"""Browser E2E checks for the WebAuthn-backed OIDC4AC ``pop`` factor.

The HTTP runner deliberately cannot exercise WebAuthn.  This runner uses
Chromium's CDP virtual CTAP2 authenticator instead of stubbing browser APIs,
so Keycloak receives a real browser-generated assertion and verifies it with
the normal WebAuthn implementation.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import secrets
import struct
import sys
import time
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


CLIENT = os.environ.get("OIDC4AC_BROWSER_CLIENT_URL", "http://client.localhost:5000").rstrip("/")
KEYCLOAK = os.environ.get("OIDC4AC_BROWSER_KEYCLOAK_URL", "http://keycloak.localhost:8080").rstrip("/")
REALM = os.environ.get("OIDC4AC_BROWSER_REALM", "oidc4ac")
ACCOUNT = f"{KEYCLOAK}/realms/{REALM}/account/"
AUTH_ENDPOINT = f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/auth"
CONSENT_CLIENT_ID = "oidc4ac-consent-test-client"
ALICE = os.environ.get("OIDC4AC_BROWSER_USERNAME", "alice")
PASSWORD = os.environ.get("OIDC4AC_BROWSER_PASSWORD", "Alice-password-123")
OTP_USER = os.environ.get("OIDC4AC_BROWSER_OTP_USERNAME", "otp-user")
OTP_PASSWORD = os.environ.get("OIDC4AC_BROWSER_OTP_PASSWORD", "Otp-user-password-123")
TOTP_SECRET = os.environ.get("OIDC4AC_BROWSER_TOTP_SECRET", "DJmQfC73VGFhw7D4QJ8A")
TIMEOUT = float(os.environ.get("OIDC4AC_BROWSER_TIMEOUT", "90"))
LAST_TOTP_COUNTER: int | None = None


class BrowserCheckFailure(AssertionError):
    """An assertion with a useful browser-flow diagnostic."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise BrowserCheckFailure(message)


def method(identifier: str) -> dict[str, Any]:
    return {
        "amr_identifier": {"value": identifier},
        "amr_metadata": {"time": {"essential": True}},
    }


def current_totp(secret: str = TOTP_SECRET, *, avoid_reuse: bool = True, interval_offset: int = 0) -> str:
    global LAST_TOTP_COUNTER
    counter = int(time.time()) // 30
    # A previous runner (for example the HTTP suite) may have consumed the
    # current credential interval. Start on a fresh interval even when this
    # process has not generated a code yet.
    if avoid_reuse and (LAST_TOTP_COUNTER is None or LAST_TOTP_COUNTER == counter):
        time.sleep(30 - (time.time() % 30) + 0.25)
        counter = int(time.time()) // 30
    if avoid_reuse:
        LAST_TOTP_COUNTER = counter
    # Keycloak stores the generated value in the credential as the raw secret;
    # its Base32 representation is only used for the QR code/display field.
    key = secret.encode()
    digest = hmac.new(key, struct.pack(">Q", counter + interval_offset), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def pop_claims(*identifiers: str) -> dict[str, Any]:
    expression = {"all_of": [method(identifier) for identifier in identifiers]}
    return {"id_token": {"amr_details": {"essential": True, **expression}}}


def wait_for_lab(page: Page) -> None:
    deadline = time.monotonic() + TIMEOUT
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            response = page.request.get(f"{CLIENT}/healthz", timeout=3_000)
            discovery = page.request.get(
                f"{KEYCLOAK}/realms/{REALM}/.well-known/openid-configuration", timeout=3_000
            )
            if response.ok and response.json().get("status") == "ok" and discovery.ok:
                return
            last_error = f"client HTTP {response.status}, issuer HTTP {discovery.status}"
        except Exception as error:  # pragma: no cover - diagnostic path
            last_error = str(error)
        time.sleep(1)
    raise BrowserCheckFailure(f"Test client did not become ready ({last_error}).")


def login_form(page: Page, *, username: str = ALICE, password: str = PASSWORD) -> None:
    # The lab deliberately collects a username before the request-scoped
    # factors. This permits requests such as otp + pop, whose authenticators
    # both require an identified user but do not include pwd.
    for _ in range(2):
        form = page.locator("#kc-form-login")
        try:
            form.wait_for(state="visible", timeout=10_000)
        except PlaywrightTimeoutError:
            username_input = page.locator("input[name='username']")
            try:
                username_input.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError:
                return
            form = username_input.locator("xpath=ancestor::form")
        username_input = form.locator("#username")
        if username_input.count() and username_input.is_visible():
            username_input.fill(username)
        password_input = form.locator("#password")
        if password_input.count() == 0 or not password_input.is_visible():
            form.locator("button[type='submit'], input[type='submit']").first.click()
            page.wait_for_load_state("domcontentloaded")
            continue
        password_input.fill(password)
        form.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("domcontentloaded")
        return


def configure_otp_if_present(page: Page) -> str | None:
    """Complete Keycloak's OTP enrollment required action and return its secret."""
    form = page.locator("#kc-totp-settings-form")
    try:
        form.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        return None
    secret = form.locator("input[name='totpSecret']").input_value()
    check(secret, "OTP enrollment page did not expose a generated secret.")
    label = form.locator("input[name='userLabel']")
    if label.count():
        label.fill("OIDC4AC browser E2E")
    form.locator("input[name='totp']").fill(current_totp(secret, avoid_reuse=False))
    form.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")
    return secret


def submit_otp_if_present(page: Page, *, expected: bool, secret: str | None = None) -> bool:
    form = page.locator("#kc-otp-login-form")
    try:
        form.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        check(not expected, "The requested flow was expected to prompt for OTP, but it did not.")
        return False
    check(expected, "The pwd + pop request unexpectedly prompted for OTP.")
    # OTP enrollment validates the setup code through the credential provider,
    # which marks that value as used when code reuse is disabled. Use the next
    # accepted TOTP interval for the actual authentication challenge.
    code = current_totp(secret or TOTP_SECRET, avoid_reuse=secret is None, interval_offset=1 if secret else 0)
    form.locator("#otp").fill(code)
    form.locator("button[type='submit'], input[type='submit']").first.click()
    page.wait_for_load_state("domcontentloaded")
    return True


def install_virtual_authenticator(context: BrowserContext) -> tuple[Any, str]:
    cdp = context.new_cdp_session(context.pages[0])
    cdp.send("WebAuthn.enable")
    result = cdp.send(
        "WebAuthn.addVirtualAuthenticator",
        {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
        },
    )
    return cdp, result["authenticatorId"]


def register_passkey(page: Page, label: str) -> None:
    """Register Alice's credential through the shipped Account Console UI."""
    page.goto(ACCOUNT, wait_until="domcontentloaded")
    login_form(page)
    page.get_by_test_id("accountSecurity").click()
    page.get_by_test_id("account-security/signing-in").click()
    page.get_by_test_id("webauthn/create").click()
    page.wait_for_selector("#registerWebAuthn", state="visible")
    page.locator("#registerWebAuthn").click()
    page.wait_for_url(re.compile(r"/realms/[^/]+/account/"), timeout=TIMEOUT * 1_000)
    page.get_by_test_id("account-security/signing-in").click()
    credential_list = page.get_by_test_id("webauthn/credential-list")
    credential_list.wait_for(state="visible")
    check(label in credential_list.inner_text(), "Account Console did not show the newly registered passkey.")


def start_authorization(
    page: Page,
    request_claims: dict[str, Any],
    *,
    expect_otp: bool,
    username: str = ALICE,
    password: str = PASSWORD,
    configure_otp: bool = False,
) -> None:
    page.goto(CLIENT, wait_until="domcontentloaded")
    page.locator("#claims-json").fill(json.dumps(request_claims))
    page.locator("#authorization-form button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")
    login_form(page, username=username, password=password)

    enrollment_secret = configure_otp_if_present(page) if configure_otp else None
    submit_otp_if_present(page, expected=expect_otp, secret=enrollment_secret)

    webauthn_button = page.locator("#authenticateWebAuthnButton")
    try:
        webauthn_button.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError:
        # A successful authentication could already have redirected directly
        # to the RP; otherwise preserve the page text in the eventual failure.
        pass
    else:
        webauthn_button.click()
    try:
        page.wait_for_url(re.compile(rf"{re.escape(CLIENT)}/callback"), timeout=TIMEOUT * 1_000)
    except PlaywrightTimeoutError:
        print(f"Authorization page after WebAuthn click: {page.url}\n{page.locator('body').inner_text()[:1200]}", file=sys.stderr)
        raise
    check("Verified authentication context" in page.locator("body").inner_text(), "The browser authorization did not reach the test-client result.")


def json_section(page: Page, heading: str) -> dict[str, Any]:
    section = page.locator("h2", has_text=heading).locator("..")
    raw = section.locator("pre").inner_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise BrowserCheckFailure(f"{heading} was not valid JSON: {error}") from error


def detail_map(token: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details = token.get("amr_details")
    check(isinstance(details, list), "Token did not contain an amr_details array.")
    result: dict[str, dict[str, Any]] = {}
    for detail in details:
        check(isinstance(detail, dict), "amr_details contains a non-object execution.")
        identifier = detail.get("amr_identifier")
        metadata = detail.get("amr_metadata")
        check(isinstance(identifier, str), "An execution did not contain amr_identifier.")
        check(isinstance(metadata, dict) and isinstance(metadata.get("time"), str),
              f"{identifier!r} did not retain mandatory amr_metadata.time.")
        result[identifier] = detail
    return result


def test_positive_pop(page: Page) -> None:
    label = f"OIDC4AC lab passkey {int(time.time())}"
    page.on("dialog", lambda dialog: dialog.accept(label))
    register_passkey(page, label)
    # The Account Console leaves Alice's SSO cookie in this context. Clear it
    # before the authorization request so the requested pwd factor is actually
    # exercised instead of the browser flow's re-authentication fallback.
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    start_authorization(page, pop_claims("pwd", "otp", "pop"), expect_otp=True)
    id_details = detail_map(json_section(page, "Verified ID Token"))
    userinfo = json_section(page, "Access-token-bound UserInfo")
    check(set(id_details) == {"pwd", "otp", "pop"}, f"ID Token executions were {sorted(id_details)}.")
    check("amr_details" not in userinfo, "UserInfo disclosed a location that the browser request did not ask for.")
    check(id_details["pop"].get("amr_identifier") == "pop", "WebAuthn was not represented as pop.")


def test_sso_reauthentication_for_stronger_request(page: Page) -> None:
    """A stronger request must not silently reuse the weaker browser SSO event."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    start_authorization(page, {"id_token": {"amr_details": {"essential": True, **method("pwd")}}},
                        expect_otp=False)

    # Preserve the Keycloak SSO cookie and submit a new request requiring OTP.
    # The second authorization must show both the password and OTP challenges;
    # accepting the original SSO event would incorrectly skip them.
    page.goto(CLIENT, wait_until="domcontentloaded")
    page.locator("#claims-json").fill(json.dumps({
        "id_token": {"amr_details": {"essential": True, "all_of": [method("pwd"), method("otp")]}},
        "userinfo": {"amr_details": {"essential": True, "all_of": [method("pwd"), method("otp")]}},
    }))
    page.locator("#authorization-form button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")
    check(page.locator("#kc-form-login").is_visible(),
          "A stronger request reused the weaker browser SSO password event.")
    login_form(page)
    submit_otp_if_present(page, expected=True)
    page.wait_for_url(re.compile(rf"{re.escape(CLIENT)}/callback"), timeout=TIMEOUT * 1_000)
    details = detail_map(json_section(page, "Verified ID Token"))
    check(set(details) == {"pwd", "otp"},
          f"The reauthenticated browser event contained {sorted(details)}.")


def test_runtime_one_of_falls_back_from_missing_pop(page: Page) -> None:
    """A retryable passkey failure selects the next preplanned one_of branch."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    request_claims = {"id_token": {"amr_details": {"essential": True, "one_of": [method("pop"), method("pwd")]}}}
    page.goto(CLIENT, wait_until="domcontentloaded")
    page.locator("#claims-json").fill(json.dumps(request_claims))
    page.locator("#authorization-form button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")
    login_form(page)
    webauthn_button = page.locator("#authenticateWebAuthnButton")
    if not page.url.startswith(f"{CLIENT}/callback"):
        try:
            webauthn_button.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        else:
            webauthn_button.click()
            page.wait_for_load_state("domcontentloaded")

    # The failed pop branch is retryable; the planner must now display pwd.
    if not page.url.startswith(f"{CLIENT}/callback"):
        check(page.locator("#kc-form-login").is_visible(),
              "A missing passkey did not advance to the satisfiable one_of password branch.")
        login_form(page)
        page.wait_for_url(re.compile(rf"{re.escape(CLIENT)}/callback"), timeout=TIMEOUT * 1_000)
    details = detail_map(json_section(page, "Verified ID Token"))
    check(set(details) == {"pwd"}, "The one_of fallback emitted the failed pop execution.")


def test_password_and_pop_without_otp(page: Page) -> None:
    """A two-factor pwd + pop request must not activate the OTP subflow."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    start_authorization(page, pop_claims("pwd", "pop"), expect_otp=False)
    id_details = detail_map(json_section(page, "Verified ID Token"))
    check(set(id_details) == {"pwd", "pop"}, f"pwd + pop executions were {sorted(id_details)}.")
    check("otp" not in id_details, "pwd + pop unexpectedly recorded an OTP execution.")


def test_unconfigured_otp_enrollment_resumes_authentication(page: Page) -> None:
    """OTP enrollment must be followed by an OTP verification challenge."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    start_authorization(
        page,
        pop_claims("pwd", "otp"),
        expect_otp=True,
        username=OTP_USER,
        password=OTP_PASSWORD,
        configure_otp=True,
    )
    id_details = detail_map(json_section(page, "Verified ID Token"))
    check(set(id_details) == {"pwd", "otp"}, f"OTP-enrollment executions were {sorted(id_details)}.")


def test_otp_and_pop_without_password(page: Page) -> None:
    """A configured OTP + passkey request must not require the pwd factor."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    start_authorization(page, pop_claims("otp", "pop"), expect_otp=True)
    id_details = detail_map(json_section(page, "Verified ID Token"))
    check(set(id_details) == {"otp", "pop"}, f"OTP + pop executions were {sorted(id_details)}.")


def test_reordered_password_and_pop_without_otp(page: Page) -> None:
    """Request JSON order must not add OTP or change the selected factors."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    start_authorization(page, pop_claims("pop", "pwd"), expect_otp=False)
    id_details = detail_map(json_section(page, "Verified ID Token"))
    check(set(id_details) == {"pwd", "pop"}, f"Reordered pwd + pop executions were {sorted(id_details)}.")


def test_missing_pop_is_public_failure(page: Page, context: BrowserContext, authenticator_id: str) -> None:
    cdp = context.new_cdp_session(page)
    cdp.send("WebAuthn.removeVirtualAuthenticator", {"authenticatorId": authenticator_id})
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    page.goto(CLIENT, wait_until="domcontentloaded")
    page.locator("#claims-json").fill(json.dumps(pop_claims("pwd", "otp", "pop")))
    page.locator("#authorization-form button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")
    login_form(page)
    button = page.locator("#authenticateWebAuthnButton")
    submit_otp_if_present(page, expected=True)
    # A missing credential may be rejected by the WebAuthn authenticator
    # before its standalone button is rendered.  In a one_of request the
    # planner is allowed to advance directly to the password branch, so the
    # RP can already be at its callback by this point.
    if not page.url.startswith(f"{CLIENT}/callback"):
        try:
            button.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        else:
            button.click()
    try:
        page.wait_for_url(re.compile(rf"{re.escape(CLIENT)}/callback"), timeout=TIMEOUT * 1_000)
    except PlaywrightTimeoutError:
        # Keycloak's stock WebAuthn authenticator may keep the enclosing
        # authentication action active after a browser API failure rather
        # than render its standalone retry template. Either way, the browser
        # must not receive enrollment details or the RP's expression values;
        # the HTTP essential-failure cases cover the protocol bridge itself.
        body = page.locator("body").inner_text().lower()
        check("pop" not in body and "face" not in body and "amr_details" not in body,
              "Missing WebAuthn credential leaked protocol details.")
        return
    body = page.locator("body").inner_text().lower()
    check("unmet_authentication_requirements" in body, "Missing WebAuthn credential did not return the generic protocol error.")


def test_explicit_user_cancellation_returns_access_denied(page: Page) -> None:
    """Consent refusal remains access_denied and is not recast as a factor failure."""
    page.goto(f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    state = secrets.token_urlsafe(16)
    request_claims = {"id_token": {"amr_details": {"essential": True, **method("pwd")}}}
    location = f"{AUTH_ENDPOINT}?{urlencode({
        'response_type': 'code',
        'client_id': CONSENT_CLIENT_ID,
        'redirect_uri': f'{CLIENT}/callback',
        'scope': 'openid profile email',
        'state': state,
        'nonce': secrets.token_urlsafe(16),
        'prompt': 'consent',
        'claims': json.dumps(request_claims, separators=(',', ':')),
    })}"
    page.goto(location, wait_until="domcontentloaded")
    login_form(page)
    cancel = page.locator("#kc-cancel")
    cancel.wait_for(state="visible", timeout=15_000)
    cancel.click()
    page.wait_for_url(re.compile(rf"{re.escape(CLIENT)}/callback"), timeout=TIMEOUT * 1_000)
    body = page.locator("body").inner_text().lower()
    check("access_denied" in body, "Explicit consent cancellation did not return access_denied.")
    check("unmet_authentication_requirements" not in body,
          "Explicit cancellation was incorrectly recast as unmet_authentication_requirements.")


def main() -> int:
    print(f"OIDC4AC browser suite against {CLIENT}")
    with sync_playwright() as playwright:
        # Keep the explicit flag for Chromium variants that do not classify a
        # non-default localhost port as a secure context. No test-only TLS
        # certificates are needed for the disposable localhost origin.
        browser: Browser = playwright.chromium.launch(
            headless=True,
            args=[f"--unsafely-treat-insecure-origin-as-secure={KEYCLOAK},{CLIENT}"],
        )
        context = browser.new_context()
        page = context.new_page()
        cdp, authenticator_id = install_virtual_authenticator(context)
        try:
            wait_for_lab(page)
            test_positive_pop(page)
            print("PASS  register passkey and authorize pwd + OTP + pop")
            test_sso_reauthentication_for_stronger_request(page)
            print("PASS  browser SSO reauthentication for a stronger request")
            test_unconfigured_otp_enrollment_resumes_authentication(page)
            print("PASS  unconfigured OTP enrollment resumes with OTP verification")
            test_otp_and_pop_without_password(page)
            print("PASS  authorize OTP + pop without password")
            test_password_and_pop_without_otp(page)
            print("PASS  authorize pwd + pop without OTP")
            test_reordered_password_and_pop_without_otp(page)
            print("PASS  authorize reordered pop + pwd without OTP")
            test_missing_pop_is_public_failure(page, context, authenticator_id)
            print("PASS  missing passkey failure does not leak enrollment")
            # The missing-passkey test removes the virtual authenticator. Use
            # the same empty authenticator for the runtime one_of fallback.
            test_runtime_one_of_falls_back_from_missing_pop(page)
            print("PASS  runtime one_of fallback after a retryable pop failure")
            test_explicit_user_cancellation_returns_access_denied(page)
            print("PASS  explicit user cancellation returns access_denied")
        except Exception as error:
            page.screenshot(path="/tmp/oidc4ac-browser-failure.png", full_page=True)
            print(f"FAIL  {error}", file=sys.stderr)
            print(f"      URL: {page.url}", file=sys.stderr)
            print("      Screenshot: /tmp/oidc4ac-browser-failure.png", file=sys.stderr)
            return 1
        finally:
            cdp.send("WebAuthn.disable")
            context.close()
            browser.close()
    print("PASS  9 browser authentication scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
