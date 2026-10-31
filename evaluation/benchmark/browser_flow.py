"""Browser helpers shared by message-sizes.py and seed-session.py.

They run inside the laboratory's browser test image, where the browser run.py
is available. authorize() answers every factor the planner presents: password,
TOTP, WebAuthn (through a virtual authenticator), and the email code read from
smtp4dev.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote, urlencode

from playwright.sync_api import Browser, Page, Playwright, TimeoutError as PlaywrightTimeoutError

import run

SMTP4DEV = os.environ.get("OIDC4AC_BROWSER_SMTP4DEV_URL", "http://localhost:5080").rstrip("/")
MAX_AGE = 3600


def compact_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def request_bytes(request_claims: dict[str, Any]) -> int:
    compact = json.dumps(request_claims, separators=(",", ":"))
    return len(urlencode({"claims": compact}).encode("utf-8"))


def located(expression: dict[str, Any]) -> dict[str, Any]:
    request = {"essential": True, **expression}
    return {"id_token": {"amr_details": request}, "userinfo": {"amr_details": request}}


def detailed_method(discovery: dict[str, Any], identifier: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"time": {"essential": True, "max_age": MAX_AGE}}
    metadata.update({name: None for name in discovery.get(f"{identifier}_metadata_supported", [])})
    method: dict[str, Any] = {"amr_identifier": {"value": identifier}, "amr_metadata": metadata}
    properties = discovery.get(f"{identifier}_properties_supported", [])
    if properties:
        method["amr_properties"] = {name: None for name in properties}
    return method


def best_case(discovery: dict[str, Any]) -> dict[str, Any]:
    return located(detailed_method(discovery, "pwd"))


def worst_case(discovery: dict[str, Any]) -> dict[str, Any]:
    return located({"all_of": [detailed_method(discovery, identifier)
                               for identifier in discovery["amr_identifiers_supported"]]})


def open_browser(playwright: Playwright) -> tuple[Browser, Page, dict[str, Any]]:
    """Launches Chromium with a virtual authenticator and registers Alice's passkey."""
    browser = playwright.chromium.launch(
        headless=True,
        args=[f"--unsafely-treat-insecure-origin-as-secure={run.KEYCLOAK},{run.CLIENT}"],
    )
    context = browser.new_context()
    page = context.new_page()
    run.install_virtual_authenticator(context)
    run.wait_for_lab(page)
    label = f"OIDC4AC passkey {int(time.time())}"
    page.on("dialog", lambda dialog: dialog.accept(label))
    run.register_passkey(page, label)
    discovery = page.request.get(f"{run.KEYCLOAK}/realms/{run.REALM}/.well-known/openid-configuration").json()
    return browser, page, discovery


def smtp_keys(page: Page) -> set[str]:
    response = page.request.get(f"{SMTP4DEV}/api/messages")
    payload = response.json()
    messages = payload if isinstance(payload, list) else payload.get("results") or []
    return {str(message.get("id")) for message in messages}


def email_code(page: Page, previous: set[str], timeout: float) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for key in smtp_keys(page) - previous:
            raw = page.request.get(f"{SMTP4DEV}/api/messages/{quote(key, safe='')}/raw").text()
            match = re.search(r"verification code\s+is\s*:?\s*(?:<[^>]+>\s*)?(\d{6})", raw, re.IGNORECASE)
            if match:
                previous.add(key)
                return match.group(1)
        time.sleep(0.5)
    return None


def authorize(page: Page, request_claims: dict[str, Any]) -> None:
    """Drives the test client and answers each factor the planner presents."""
    seen_messages = new_session(page)
    page.goto(run.CLIENT, wait_until="domcontentloaded")
    page.locator("#claims-json").fill(json.dumps(request_claims))
    page.locator("#authorization-form button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")
    complete_factors(page, seen_messages)
    run.check("Verified authentication context" in page.locator("body").inner_text(),
              "The authorization did not reach the test-client result.")


def new_session(page: Page) -> set[str]:
    """Ends the current Keycloak session and returns the emails already received."""
    page.goto(f"{run.KEYCLOAK}/realms/{run.REALM}/protocol/openid-connect/logout", wait_until="domcontentloaded")
    page.context.clear_cookies()
    return smtp_keys(page)


def complete_factors(page: Page, seen_messages: set[str]) -> None:
    """Answers each factor the planner presents until Keycloak redirects to the RP callback."""
    run.login_form(page)
    for _ in range(8):
        if page.url.startswith(f"{run.CLIENT}/callback"):
            break
        otp_form = page.locator("#kc-otp-login-form")
        webauthn = page.locator("#authenticateWebAuthnButton")
        try:
            page.locator("#kc-otp-login-form, #authenticateWebAuthnButton").first.wait_for(state="visible", timeout=15_000)
        except PlaywrightTimeoutError:
            page.wait_for_url(re.compile(rf"{re.escape(run.CLIENT)}/callback"), timeout=run.TIMEOUT * 1_000)
            break
        if webauthn.is_visible():
            # The virtual authenticator answers immediately and the page may
            # navigate while the click is still settling.
            try:
                webauthn.click(no_wait_after=True, timeout=5_000)
            except PlaywrightTimeoutError:
                pass
        else:
            # The email factor reuses Keycloak's OTP form; a new message in
            # smtp4dev identifies it, otherwise the form asks for the TOTP code.
            code = email_code(page, seen_messages, 3) or run.current_totp()
            otp_form.locator("#otp").fill(code)
            otp_form.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(re.compile(rf"{re.escape(run.CLIENT)}/callback"), timeout=run.TIMEOUT * 1_000)
