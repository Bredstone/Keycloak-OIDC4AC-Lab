"""Interactive relying party and request workbench for native OIDC4AC.

Copyright 2026 Red Hat, Inc. and/or its affiliates
and other contributors as indicated by the @author tags.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
from threading import Lock
import time
from typing import Any

import requests
from authlib.integrations.flask_client import OAuth
from flask import Flask, jsonify, render_template, request, session, url_for


ISSUER = os.environ.get("OIDC_ISSUER", "http://keycloak.localhost:8080/realms/oidc4ac")
CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "oidc4ac-test-client")
CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "oidc4ac-lab-client-secret")
SMTP4DEV_URL = os.environ.get("SMTP4DEV_URL", "http://localhost:5080")
TOTP_SECRET = os.environ.get("OIDC4AC_TOTP_SECRET", "DJmQfC73VGFhw7D4QJ8A")
# A public deployment may terminate TLS in a reverse proxy while this Flask process
# remains on a private loopback port. When set, use the public URL explicitly
# for the OAuth callback instead of deriving it from the internal request.
PUBLIC_URL = os.environ.get("OIDC4AC_PUBLIC_URL", "").rstrip("/")

# These caches deliberately only live for the lifetime of this disposable lab
# process. Keeping the full request server-side also keeps experimental raw
# requests out of the browser's signed Flask session cookie.
AUTHORIZATION_CACHE: dict[str, dict[str, Any]] = {}
TOKEN_CACHE: dict[str, dict[str, Any]] = {}
CACHE_LOCK = Lock()
CACHE_TTL_SECONDS = 15 * 60

DEFAULT_CLAIMS: dict[str, Any] = {
    "id_token": {
        "amr_details": {
            "essential": True,
            "amr_identifier": {"value": "pwd"},
            "amr_metadata": {"time": {"essential": True}},
            "amr_properties": {"pwd_derivation_algorithm": None},
        }
    },
    "userinfo": {
        "amr_details": {
            "essential": True,
            "amr_identifier": {"value": "pwd"},
            "amr_metadata": {"time": {"essential": True}},
            "amr_properties": {"pwd_derivation_algorithm": None},
        }
    },
}


class ClaimsValidationError(ValueError):
    """A local, actionable error while composing the authorization request."""


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False)


def prune_caches() -> None:
    """Bound the disposable in-memory state used by concurrent demo sessions."""
    cutoff = time.time() - CACHE_TTL_SECONDS
    with CACHE_LOCK:
        for cache in (AUTHORIZATION_CACHE, TOKEN_CACHE):
            expired = [key for key, value in cache.items() if value.get("created_at", 0) < cutoff]
            for key in expired:
                cache.pop(key, None)


def current_totp(secret: str = TOTP_SECRET) -> tuple[str, int]:
    """Return the current disposable lab TOTP and seconds until rotation."""
    now = int(time.time())
    counter = now // 30
    digest = hmac.new(secret.encode(), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}", 30 - (now % 30)


def decoded_access_token(token: Any) -> dict[str, Any]:
    """Decode only the JWT payload for a diagnostic assertion page.

    The bearer token itself is never rendered or returned. The relying party
    has already received and validated the authorization response; this
    payload view lets the disposable E2E suite assert that protocol-specific
    authentication details are not copied into access tokens.
    """
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    try:
        payload = token.split(".", 2)[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def parse_claims(raw_claims: str | None) -> dict[str, Any]:
    """Parse a user-authored Claim Request Object without changing its meaning."""
    if raw_claims is None or not raw_claims.strip():
        raise ClaimsValidationError("Provide a Claim Request Object before starting authorization.")
    if len(raw_claims.encode("utf-8")) > 64_000:
        raise ClaimsValidationError("The Claim Request Object is limited to 64 KB in this local lab.")
    try:
        claims = json.loads(raw_claims)
    except json.JSONDecodeError as error:
        raise ClaimsValidationError(
            f"The Claim Request Object is not valid JSON (line {error.lineno}, column {error.colno})."
        ) from error
    if not isinstance(claims, dict):
        raise ClaimsValidationError("The Claim Request Object must be a top-level JSON object.")
    return claims


def home_response(raw_claims: str | None = None, error: str | None = None, status: int = 200) -> tuple[str, int] | str:
    prune_caches()
    page = render_template(
        "home.html",
        issuer=ISSUER,
        smtp4dev_url=SMTP4DEV_URL,
        raw_claims=raw_claims if raw_claims is not None else pretty_json(DEFAULT_CLAIMS),
        error=error,
    )
    return (page, status) if status != 200 else page


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "local-development-only-change-me")
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("OIDC4AC_PUBLIC_HTTPS", "false").lower() == "true"
    oauth = OAuth(app)
    oauth.register(
        name="keycloak",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        server_metadata_url=f"{ISSUER}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email"},
    )

    @app.get("/healthz")
    def healthz() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.get("/otp")
    def otp_helper() -> str:
        code, remaining = current_totp()
        return render_template(
            "otp.html",
            username="alice",
            code=code,
            remaining=remaining,
            secret_base32=base64.b32encode(TOTP_SECRET.encode()).decode().rstrip("="),
        )

    @app.get("/tools")
    def factor_tools() -> str:
        """Provide one navigation point for the disposable factor helpers."""
        return render_template(
            "tools.html",
            smtp4dev_url=SMTP4DEV_URL,
            account_url=f"{ISSUER.rstrip('/')}/account",
        )

    @app.get("/otp-code")
    def otp_code() -> tuple[dict[str, Any], int]:
        code, remaining = current_totp()
        return {"code": code, "remaining": remaining}, 200

    @app.get("/discovery")
    def discovery() -> tuple[dict[str, Any], int] | Any:
        """Expose discovery-derived builder suggestions without browser CORS concerns."""
        try:
            return jsonify(builder_discovery_metadata())
        except requests.RequestException:
            return jsonify({"error": "The issuer discovery document is unavailable."}), 502

    @app.get("/")
    def home() -> str:
        return home_response()

    @app.post("/preview")
    def preview() -> tuple[str, int] | str:
        raw_claims = request.form.get("claims_json")
        try:
            claims = parse_claims(raw_claims)
        except ClaimsValidationError as error:
            return home_response(raw_claims, str(error), 400)
        return render_template("preview.html", claims=pretty_json(claims))

    @app.post("/login")
    def login() -> Any:
        raw_claims = request.form.get("claims_json")
        omit_claims = request.form.get("omit_claims") == "on"
        if omit_claims:
            # The ordinary-login E2E case deliberately omits the OIDC
            # `claims` parameter. The visual client always submits JSON, but
            # this switch lets the disposable test driver exercise the true
            # no-claims browser path as well.
            claims = {}
        else:
            try:
                claims = parse_claims(raw_claims)
            except ClaimsValidationError as error:
                return home_response(raw_claims, str(error), 400)

        nonce = secrets.token_urlsafe(32)
        context_id = secrets.token_urlsafe(24)
        prune_caches()
        with CACHE_LOCK:
            AUTHORIZATION_CACHE[context_id] = {
                "claims": claims,
                "nonce": nonce,
                "created_at": time.time(),
            }
        parameters: dict[str, str] = {"nonce": nonce}
        if request.form.get("offline_access") == "on":
            parameters["scope"] = "openid profile email offline_access"
        if not omit_claims:
            parameters["claims"] = json.dumps(claims, separators=(",", ":"))
        if request.form.get("prompt_login") == "on":
            parameters["prompt"] = "login"
        callback_url = f"{PUBLIC_URL}/callback" if PUBLIC_URL else url_for("callback", _external=True)
        # Supplying our own state gives every tab/request an independent
        # correlation key. It avoids a shared session slot overwriting a
        # pending authorization when users use the client concurrently.
        return oauth.keycloak.authorize_redirect(callback_url, state=context_id, **parameters)

    @app.get("/callback")
    def callback() -> tuple[str, int] | str:
        if request.args.get("error"):
            return render_template(
                "error.html",
                error=request.args["error"],
                description=request.args.get("error_description", "No public description was returned."),
            )
        context_id = request.args.get("state")
        with CACHE_LOCK:
            context = AUTHORIZATION_CACHE.pop(context_id, None) if context_id else None
        if context is None:
            return render_template(
                "error.html", error="missing_context", description="The local relying-party session has expired."
            ), 400
        try:
            token = oauth.keycloak.authorize_access_token()
            id_token = dict(oauth.keycloak.parse_id_token(token, nonce=context["nonce"]))
            userinfo = dict(oauth.keycloak.userinfo(token=token))
        except Exception:
            app.logger.exception("OIDC authorization response verification failed")
            return render_template(
                "error.html",
                error="token_validation_failed",
                description="The authorization response could not be verified.",
            ), 400

        result_id = secrets.token_urlsafe(24)
        with CACHE_LOCK:
            TOKEN_CACHE[result_id] = {
                "refresh_token": token.get("refresh_token"),
                "claims": context["claims"],
                "created_at": time.time(),
            }
        session["oidc4ac_result"] = result_id
        return render_result(context["claims"], id_token, userinfo, token.get("access_token"), True,
                             "Authorization code response", result_id)

    @app.post("/refresh")
    def refresh() -> tuple[str, int] | str:
        prune_caches()
        result_id = request.form.get("result_id") or session.get("oidc4ac_result")
        with CACHE_LOCK:
            cached = TOKEN_CACHE.get(result_id)
        if not cached or not cached.get("refresh_token"):
            return render_template(
                "error.html", error="no_refresh_token", description="Start a new authorization request to test refresh."
            ), 400
        try:
            token = oauth.keycloak.fetch_access_token(
                grant_type="refresh_token", refresh_token=cached["refresh_token"]
            )
            # A refresh-derived ID Token is validated as a token response, not
            # as the original browser authorization response. OIDC does not
            # require it to repeat the original nonce.
            id_token = dict(oauth.keycloak.parse_id_token(token, nonce=None))
            userinfo = dict(oauth.keycloak.userinfo(token=token))
        except Exception:
            app.logger.exception("OIDC refresh response verification failed")
            return render_template(
                "error.html",
                error="refresh_failed",
                description="The refreshed token response could not be verified.",
            ), 400
        cached["refresh_token"] = token.get("refresh_token", cached["refresh_token"])
        with CACHE_LOCK:
            cached["created_at"] = time.time()
        return render_result(cached["claims"], id_token, userinfo, token.get("access_token"), True,
                             "Refresh token response", result_id)

    return app


def discovery_metadata() -> dict[str, Any]:
    document = issuer_discovery_document()
    return {
        name: value
        for name, value in document.items()
        if name == "claims_supported" or name.startswith(("amr_", "pwd_", "otp_", "pop_"))
    }


def issuer_discovery_document() -> dict[str, Any]:
    response = requests.get(f"{ISSUER}/.well-known/openid-configuration", timeout=5)
    response.raise_for_status()
    return response.json()


def builder_discovery_metadata() -> dict[str, Any]:
    """Normalize the discovery members used by the visual request editor."""
    document = issuer_discovery_document()
    identifiers = document.get("amr_identifiers_supported", [])
    if not isinstance(identifiers, list):
        identifiers = []

    methods: dict[str, dict[str, Any]] = {}
    for identifier in identifiers:
        if not isinstance(identifier, str):
            continue
        property_names = document.get(f"{identifier}_properties_supported", [])
        if not isinstance(property_names, list):
            property_names = []
        metadata_names = document.get(f"{identifier}_metadata_supported", [])
        if not isinstance(metadata_names, list):
            metadata_names = []
        properties: dict[str, dict[str, list[Any]]] = {}
        for property_name in property_names:
            if not isinstance(property_name, str):
                continue
            values = document.get(f"{property_name}_values_supported", [])
            properties[property_name] = {"values": values if isinstance(values, list) else []}
        metadata: dict[str, dict[str, list[Any]]] = {}
        for metadata_name in metadata_names:
            if not isinstance(metadata_name, str):
                continue
            values = document.get(f"{metadata_name}_values_supported", [])
            metadata[metadata_name] = {"values": values if isinstance(values, list) else []}
        methods[identifier] = {"metadata": metadata, "properties": properties}

    return {"identifiers": sorted(methods), "methods": methods}


def render_result(
    claims: dict[str, Any], id_token: dict[str, Any], userinfo: dict[str, Any], access_token: Any,
    allow_refresh: bool, source: str, result_id: str
) -> str:
    return render_template(
        "result.html",
        claims=pretty_json(claims),
        discovery=pretty_json(discovery_metadata()),
        id_token=pretty_json(id_token),
        access_token=pretty_json(decoded_access_token(access_token)),
        userinfo=pretty_json(userinfo),
        allow_refresh=allow_refresh,
        source=source,
        result_id=result_id,
    )


if __name__ == "__main__":
    create_app().run(host=os.environ.get("OIDC4AC_CLIENT_BIND_HOST", "127.0.0.1"),
                     port=int(os.environ.get("PORT", "5000")))
