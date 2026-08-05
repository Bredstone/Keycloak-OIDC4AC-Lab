# Troubleshooting

## Docker or first-build failures

**Docker daemon is unavailable.** Start Docker and check `docker info`, then
rerun `./dev.sh run`. The Maven build happens inside Docker, so installing Java
on the host does not fix a stopped daemon.

**The first run takes a long time.** The wrapper clones the configured
Keycloak fork and downloads Maven dependencies before starting services. Later
runs reuse `.runtime/keycloak-source`, `.runtime/maven-cache`, and `.build/`.

**The downloaded source is not the code I expected.** Check:

```bash
./dev.sh status
printf '%s\n' "${OIDC4AC_LAB_KEYCLOAK_REPO:-remote fork}"
```

Use `OIDC4AC_LAB_KEYCLOAK_REPO=/absolute/path/to/checkout` for an intentional
local checkout, or set `OIDC4AC_LAB_KEYCLOAK_REPO_URL` and
`OIDC4AC_LAB_KEYCLOAK_REF` before `./dev.sh build`.

## Ports and stale processes

**Address already in use.** Run `./dev.sh status` and `./dev.sh down`. The
default `run` command cleans this lab's Compose services and a Keycloak process
on its configured port; `--no-kill` intentionally does not stop existing
services or processes. Choose a different
`OIDC4AC_LAB_HTTP_PORT`/`OIDC4AC_LAB_CLIENT_PORT` when another application must
remain online.

**The browser points to an older server.** Stop the old process, clear the
browser's cookies for `keycloak.localhost` and `client.localhost`, then start
the lab again. The workbench displays the issuer it actually discovered.

## Login and Account Console

**A normal login fails with an OIDC4AC requirement error.** An ordinary OIDC
request without a `claims` parameter must use the normal password branch. Check
that the realm's browser flow has the planner and factor container configured
as described in [browser-factor-planning](browser-factor-planning.md), and that
the planner leaves an unplanned request on its normal alternative.

**The Account Console says “Something went wrong”.** Verify that the login
request did not contain stale OIDC4AC semantics, that the regular server is the
one on port 8080, and that Alice has the imported Account client roles. A
private browser window alone does not replace stopping an old Keycloak process.

**The WebAuthn warning mentions `requireResidentKey`.** This is a Keycloak
policy deprecation warning, not an OIDC4AC request failure. The lab's browser
tests use the current virtual CTAP2 path; update a realm's WebAuthn policy to
`residentKey` when maintaining a long-lived deployment.

## OTP, email, and passkeys

**OTP + password returns `unmet_authentication_requirements`.** Check that the
OTP helper code is fresh, that Alice's imported OTP credential is present, and
that the request is using the current realm/client. The helper rotates every
30 seconds; do not reuse a code after a completed authorization.

**An account without OTP is asked to enroll and then fails.** That is the
expected enrollment regression path: the browser completes the required action
and the resumed authentication must still perform OTP verification before a
`pwd + otp` essential request can succeed. The dedicated browser suite covers
this with `otp-user`.

**Email code does not arrive.** Open <http://localhost:5080>, confirm the
`smtp4dev` service is running with `docker compose ps`, and check the imported
realm SMTP host/port. Rebuild the provider with `./dev.sh provider-build` if
the email method is absent from Discovery.

**A `pop` request prompts for another factor.** The HTTP runner cannot fake
WebAuthn. Use `./dev.sh test-browser` or register a passkey through the Account
Console in the browser profile. The planner can only use a `pop` subflow that
is configured in the realm.

## Tokens, refresh, and errors

**Refresh/re-check returns `refresh_failed`.** Start a new authorization with
the current test-client container, keep the original refresh-token cache, and
do not rebuild the Flask container between the authorization and re-check.
Refresh-derived responses are tied to the original grant snapshot; they do not
reconstruct authentication details from mutable session state. Inspect the
Keycloak log with `./dev.sh logs` and the result page's original request before
retrying.

**The error is `unmet_authentication_requirements`.** This is intentionally
generic for an unsatisfied essential method, property, disclosure policy, or
runtime verification. The public response must not tell the RP whether the
user lacked enrollment or the method was unavailable.

**The error is `invalid_request`.** Check JSON syntax, non-empty logical
arrays, exactly one expression operator per node, local constraint types, and
the mandatory `amr_metadata.time` request shape. The workbench's raw editor is
the exact JSON sent to the OIDC endpoint.

## Test failures

Run the smallest relevant command first:

```bash
./dev.sh verify
./dev.sh test-http
./dev.sh test-browser
```

For a clean rebuild, use `./dev.sh clean` and then `./dev.sh run`; this removes
only generated runtime/build state. If a test still fails, preserve the
command output, the Keycloak log, the selected Keycloak source/ref, and the
sanitized request JSON before opening an issue. Never attach access or refresh
tokens.
