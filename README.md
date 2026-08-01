# OIDC4AC Native Feature Lab

This standalone lab exercises the native OIDC4AC implementation in a separate
Keycloak checkout. It deliberately reuses the PoC's familiar realm, `alice`
user, `oidc4ac-test-client`, and browser-facing Flask client, but it does not
load the old PoC provider JAR or custom authenticators.

The repository is organized by responsibility: `config/` contains realm
fixtures, `test-client/` is the relying party, `e2e/` contains black-box HTTP
and browser runners, `providers/` contains optional provider examples,
`scripts/` contains lifecycle checks, and `docs/` contains protocol and
coverage notes. `.runtime/` and `.build/` are generated local state. The
optional email provider fixture is preserved under
`providers/oidc4ac-test-email/`; it is not loaded by the default realm.

## Prerequisites

- Docker with Docker Compose v2, for the test client;
- Java 21 and Maven prerequisites needed to build the Keycloak checkout; and
- `curl`, `jq`, and the development dependencies in `requirements-dev.txt`.

`*.localhost` resolves to the loopback address in modern browsers. The Compose
client maps `keycloak.localhost` to Docker's host gateway so its issuer, token,
and browser URLs all use the same host name.

## One-command workflow

From the lab root, `dev.sh` builds the local Keycloak checkout when needed,
starts Keycloak and the test client, and keeps generated state under the
ignored `.runtime/` and `.build/` directories:

```bash
./dev.sh
```

The same wrapper exposes the common lifecycle, verification, and test commands:

```bash
./dev.sh status         # show service and process status
./dev.sh logs           # show recent logs
./dev.sh verify         # run discovery/readiness checks
./dev.sh lint           # run Python, shell, XML, and Java formatting checks
./dev.sh provider-build # compile the optional email provider (target/ is ignored)
./dev.sh test-http      # run HTTP end-to-end scenarios
./dev.sh test-browser   # run virtual-CTAP2 browser scenarios
./dev.sh test-disabled  # verify the realm feature gate
./dev.sh test           # run all lab suites
./dev.sh down           # stop services
./dev.sh clean          # stop services and remove generated state
```

The Keycloak checkout defaults to the sibling directory
`../keycloak-OIDC4AC` (relative to the lab root). Set
`OIDC4AC_LAB_KEYCLOAK_REPO` to override it. Set
`OIDC4AC_LAB_SKIP_BUILD=true` after the first successful build to reuse the
prepared distribution archive.

Install the development lint dependency once with:

```bash
python3 -m pip install -r requirements-dev.txt
```

## Manual lifecycle

Set `OIDC4AC_LAB_KEYCLOAK_REPO` to the Keycloak source checkout that contains
the OIDC4AC implementation. When the repositories are sibling directories,
the default is already correct:

```bash
export OIDC4AC_LAB_KEYCLOAK_REPO=../keycloak-OIDC4AC
```

In one terminal, build that checkout, extract a new disposable server, import
the realm, and start it with the native feature enabled:

```bash
bash scripts/start-keycloak.sh
```

After a successful build, set `OIDC4AC_LAB_SKIP_BUILD=true` to reuse the
existing distribution archive for a later lab restart.

`OIDC4AC_LAB_HTTP_PORT` changes the Keycloak port when an isolated local run
is useful. Set the same issuer in Compose with `OIDC4AC_LAB_ISSUER`, and use
`OIDC4AC_LAB_CLIENT_PORT` for a second test-client port. The import permits the
default ports 5000, 5001, and 5002 for that purpose.

The local administrator defaults to `admin / admin`. Override it before
starting if required:

```bash
export OIDC4AC_LAB_ADMIN_PASSWORD='a-local-development-password'
bash scripts/start-keycloak.sh
```

In another terminal, start the relying party:

```bash
docker compose up --build
```

Run the automated HTTP end-to-end suite after both services are ready:

```bash
docker compose --profile e2e run --build --rm e2e
```

The HTTP runner defaults to the regular lab (`keycloak.localhost:8080` and
`client.localhost:5000`). To run it directly from the host, use:

```bash
OIDC4AC_E2E_CLIENT_URL=http://localhost:5000 \
OIDC4AC_E2E_ISSUER=http://localhost:8080/realms/oidc4ac \
python3 e2e/http/run.py
```

The WebAuthn browser suite is a separate profile. It starts its own disposable
Keycloak and Flask client on dedicated localhost ports, then uses Chromium's
virtual CTAP2 authenticator to register a passkey through the Account Console
and authorize real pop-backed requests:

```bash
docker compose --profile browser-e2e run --build --rm browser-e2e
```

The browser profile copies the prepared `.build/keycloak-26.7.0.tar.gz` archive
into its temporary Keycloak image, so build the checkout first (the normal
`scripts/start-keycloak.sh` command prepares this archive). It is isolated from the regular
localhost:5000 client and native server process.

The suite submits requests through this Flask test client, follows the actual
browser authorization-code redirects, fills Keycloak's password and OTP forms,
and asserts the decoded result pages. It covers Discovery-driven suggestions,
password and OTP `all_of`, `one_of`, nested expressions, ordinary OIDC login
without a `claims` parameter, best-effort unsupported methods, single-location
ID Token/UserInfo disclosure, malformed logical grammar, ordinary SSO reuse,
independent projections of one complete event, property constraints, generic
essential failures, and refresh snapshot reuse. The `pop` browser profile
covers `pwd + OTP + pop`, `otp + pop` without `pwd`, `pwd + pop` without OTP,
and reordered `pop + pwd` without OTP using a real virtual CTAP2 authenticator;
the HTTP runner intentionally does not fake WebAuthn. It also signs in as the imported
`otp-user` (which has no OTP credential), completes the real OTP enrollment
required action, and verifies that the same authorization resumes with an OTP
verification challenge before issuing `pwd + otp`. The browser suite also
verifies that a missing virtual credential does not disclose enrollment or
request details.
OIDC4AC-specific SSO reauthentication after an event fails a new essential
requirement remains a separate browser-flow scenario. The HTTP runner currently
reports 36 scenarios, including realm enablement gates, structured optional
metadata, identifier/value/numeric constraints, invalid client/redirect checks,
disclosure policy enforcement, query/fragment/form-post and signed JARM
response-mode errors, concurrent same-SSO grant projection isolation, repeated
method execution, offline refresh snapshot reuse, old-grant
immutability, and Authentication-tab admin API configuration. The browser
runner reports 9 scenarios, including runtime `one_of` fallback after a missing
passkey and explicit consent cancellation, which must return `access_denied`
rather than an OIDC4AC requirement error.

Open `http://client.localhost:5000`. Sign in as
`alice / Alice-password-123`. The workbench starts with **Essential password**
delivered to both locations.

Alice is also assigned the minimum built-in Account client roles, so the
Keycloak Account Console can load after login.

The imported realm already selects the **OIDC4AC lab browser** flow. It places
the normal cookie authenticator and an **OIDC4AC browser forms** subflow as
alternatives. Inside the latter, a required built-in **Username Form** first
identifies the End-User, then the **OIDC4AC factor planner** appears
immediately before the required `oidc4ac-factors` container. The container
exposes the `pwd`, `otp`, and `pop` factor subflows, in that realm-defined
priority order. The request controls which of those configured factors are
attempted; it cannot introduce a new provider or change their realm
configuration.

When the Admin Console is running with the Admin UI extension surface enabled,
the **Realm settings → OIDC4AC** tab exposes the realm enable switch, realm
disclosure default, and planner status. It discovers supported factors and
optional fields from OIDC Discovery, and lets an administrator choose realm
defaults without typing property paths. Disabling the switch removes OIDC4AC
discovery metadata and runtime processing for that realm while retaining the
configured policies. Planner execution and factor-flow wiring are configured
in the normal **Authentication → Flows** UI; the OIDC4AC page only reports
whether an enabled planner is present. Each OpenID Connect client has an
**OIDC4AC** tab for an inherit/selected/none disclosure override. The
underlying endpoint is `/admin/realms/{realm}/ui-ext/oidc4ac`.

An ordinary login with no `amr_details` Claim Request Object still works: the
Username Form identifies the user, the planner leaves the container unplanned,
and its normal first alternative, `oidc4ac:pwd`, presents the standard
password screen. This includes the Account Console login. The separate
Username Form is important for requests such as `otp + pop`: both of those
authenticators require an identified user, but neither is responsible for
collecting a username. Username collection is not recorded as an AMR method.

## Optional email provider

The disposable email authenticator is a normal Maven project so IDEs can
resolve the Keycloak APIs and service descriptors. It uses the adjacent
Keycloak checkout as its Maven parent and keeps Keycloak dependencies in
`provided` scope; no Keycloak classes are bundled in its JAR. Build it when
needed with:

```bash
./dev.sh provider-build
```

The JAR is written to `providers/oidc4ac-test-email/target/`, which is ignored
by Git. The default realm does not install or configure this fixture. It is
intended for custom-provider integration experiments and can be copied into a
disposable Keycloak image or mounted into `providers/` during a test run.

## Request workbench

The left-hand visual builder is intended for ordinary experiments:

- The client loads method identifiers and profile property names from the
  issuer's OIDC Discovery document. They are offered as suggestions and used
  to prefill a new property; values outside Discovery remain available for
  negative tests.
- Select a starting scenario, add factors or logical groups, and use the
  arrows to reorder sibling nodes. A node's position is JSON order inside its
  logical expression; it is not an instruction for Keycloak to run
  authenticators in that order.
- Choose `all_of` or `one_of` at the root or inside a group. Groups can be
  nested recursively, and the whole `amr_details` Claim can be essential.
- Choose the ID Token, UserInfo, or both as disclosure locations. The visual
  builder creates the same projection in each selected location.
- Request a method's mandatory execution time, apply a locally essential
  `max_age`, and add method-property constraints. Properties can be requested
  when available, required to be present, constrained to a value or set of
  values, or given a numeric range.

Click **Apply builder to JSON** to update the right-hand Claim Request Object.
That JSON is always the submitted source of truth: edit it directly for
different projections per delivery location. Use **Load JSON into builder** to
bring a recursive method/`all_of`/`one_of` expression back into the visual
editor; it uses the first requested delivery projection.

The response page shows the requested Claim Request Object, feature discovery,
the verified ID Token, and UserInfo. Use its refresh button to verify that the
original event time is reused. Rebuilding the Flask container clears its local
refresh-token cache, so start a new authorization before using refresh after a
rebuild. The password property's omission is permitted when the current
credential model cannot provide a complete truthful `amr_properties` object.

## Smoke check

Once both services are up, run:

```bash
bash scripts/verify.sh
```

It verifies discovery advertises `amr_details`, the native `pwd`, `otp`, and
`pop` identifiers, safe password and OTP profile properties, finite OTP mode,
format, and delivery-method vocabularies, and no value enumeration for the
open derivation-algorithm domain.

## Expected protocol cases

- **Essential / best-effort password**: contrast an essential Claim with a
  best-effort preference, including independently local constraints.
- **Fresh password**: adds a locally essential `max_age` constraint for the
  actual execution time.
- **Password and OTP / password or OTP**: exercise `all_of` and `one_of`
  without selecting or disclosing an artificial branch.
- **Nested methods**: builds `(pwd AND otp) OR pop` to exercise recursive
  expression handling in both the client and Keycloak request parser.
- **Password properties**: request an available property or require it to be
  present. Essential properties can produce the generic unmet-requirements
  result when Keycloak cannot truthfully disclose a complete object.
- **Unsupported method**: returns the generic
  `unmet_authentication_requirements` error; it must not disclose enrollment or
  method availability.

The lab configures OTP and WebAuthn factor subflows. Alice has a disposable
pre-enrolled TOTP credential so password-and-OTP scenarios work immediately;
the separate `otp-user / Otp-user-password-123` fixture intentionally has no
OTP credential and is used only by the browser enrollment regression. Both
fixtures are disposable and should not be copied to a real realm. The
end-to-end runner generates its codes from that local test seed and waits
for a fresh 30-second code window at startup and between independent OTP
scenarios, so separate runner processes cannot replay a consumed code. Do not
copy that credential seed to a real realm. Enrol a WebAuthn credential through
the Keycloak administration console before manually requesting `pop`.

Passwordless passkey conditional UI is disabled for this disposable realm. It
would otherwise let the standard username/password form complete using a
passkey, which truthfully produces `pop` rather than the `pwd` event selected
by the lab's password factor. The dedicated `oidc4ac:pop` factor remains
available for explicit `pop` requests.

## Dispose of runtime state

When the lab was started with the wrapper, stop it with:

```bash
./dev.sh down
```

The generated runtime and distribution state remains under `.runtime/` and
`.build/`, both ignored by Git. Remove that disposable state with
`./dev.sh clean` when it is no longer needed. Docker's test-client image can
be removed with the normal Docker commands if desired.
