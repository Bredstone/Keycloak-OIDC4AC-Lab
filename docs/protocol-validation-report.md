# OIDC4AC Phase One Protocol Validation Report

## Status

The author clarifications PD-001 through PD-010 make an experimental Keycloak
implementation feasible. The published draft at
`fc7c2c5d5155530cd4b71ee44f37cf11e2a578c2` was not independently implementable
without those decisions. As of 2026-08-01, the covered protocol paths have
passed 55 focused unit tests, 36 real authorization-code HTTP scenarios, nine
browser/WebAuthn scenarios, and five focused Arquillian authorization
integration tests. The separate provider fixture and its integration source
are preserved under `providers/` and `tests/integration/`. This is an
evidence-backed validation report, not
a claim that arbitrary Keycloak deployments or all hardware authenticators are
bug-free.

## Implementable behavior

Keycloak can parse the approved recursive request grammar, evaluate one
immutable authentication event, combine essential ID Token and UserInfo
requirements, project locations independently, preserve method execution time
for SSO, advertise safe native capabilities, and integrate a sanitized OIDC
error path. An opt-in browser factor planner can choose an ordered subset of
realm-configured factor subflows for an arbitrary `all_of`, choose a
deterministic feasible `one_of` branch, and safely advance to a preplanned
fallback branch after a terminal non-cancellation failure. A private SPI keeps
method-specific credential facts out of the OIDC parser and token code.

The native mappings are conservative: password, OTP, and verified WebAuthn are
recognized; only `pop` is asserted for WebAuthn. Password details are limited
to safe derivation metadata when available. A verified browser OTP execution
carries its selected credential only to the private adapter, which reads public
credential data and emits safe mode, length, format, delivery, and applicable
TOTP-period properties without accessing secret data.

## Verified execution

The disposable lab enables `oidc4ac:v1` dynamically and drives the actual
authorization-code flow through the test client. Its HTTP suite covers ordinary
OIDC, malformed grammar (including missing `amr_metadata.time`), nested Boolean
expressions, null claims, identifier/value/numeric constraints, claim-location
projections, immutable refresh snapshots, concurrent grant isolation, SSO and
`max_age` reauthentication, generic essential failures, invalid client/redirect
validation, Authentication-tab flow configuration, realm enablement, structured
metadata, realm/client disclosure-policy enforcement, query/fragment/form-post
and signed JARM errors, expression-free essential claims, password credential
metadata projection, and the discovery workbench. Its browser suite uses
Chromium's virtual CTAP2 authenticator for
passkey registration/assertion and covers pwd+OTP+pop, OTP enrollment resume,
OTP+pop without password, pwd+pop without OTP, reordered factors, and missing
passkey privacy behavior and explicit user cancellation. A packaged test-only
email authenticator plus `AuthenticationMethodDetailsProvider` also proves the
SPI can advertise capabilities and emit a secret-free event description through
the real Keycloak flow and token pipeline. The planner accepts both imported
`oidc4ac:<identifier>` aliases and the Admin REST-safe `oidc4ac-<identifier>` form.

The focused Arquillian suite also decrypts an RSA-OAEP/A256GCM encrypted JARM
error and verifies the generic `unmet_authentication_requirements` payload.
The packaged email provider emits evidence-bearing `trust_framework` and
`assurance_level` metadata, proving that custom providers can contribute
open-valued metadata through discovery, planning, and token projection.

The Admin Console integration test opens the Realm settings → OIDC4AC
policy editor and verifies its flow-integration, dynamic capability, and
realm/client disclosure controls.

The following commands passed on 2026-08-01 (the Keycloak Maven commands run
from the implementation checkout named by `OIDC4AC_LAB_KEYCLOAK_REPO`; the
other commands run from this lab repository):

```bash
(cd "$OIDC4AC_LAB_KEYCLOAK_REPO" && ./mvnw -pl services -am -Dskip.pnpm=true \
  -Dtest='org.keycloak.authentication.authenticators.oidc4ac.OIDC4ACFactorPlannerAuthenticatorTest,org.keycloak.protocol.oidc4ac.AmrDetailsRequestParserTest,org.keycloak.protocol.oidc4ac.OIDC4ACReauthenticationTest,org.keycloak.protocol.oidc4ac.delivery.AmrDetailsProjectionTest,org.keycloak.protocol.oidc4ac.discovery.OIDC4ACDiscoveryMetadataTest,org.keycloak.protocol.oidc4ac.discovery.CustomAuthenticationMethodDetailsProviderTest,org.keycloak.protocol.oidc4ac.disclosure.OIDC4ACDisclosurePolicyTest,org.keycloak.protocol.oidc4ac.error.OIDC4ACAuthenticationFailureBridgeTest,org.keycloak.protocol.oidc4ac.event.AuthenticationEventSnapshotCodecTest,org.keycloak.protocol.oidc4ac.event.AuthenticationEventSnapshotStoreTest,org.keycloak.protocol.oidc4ac.flow.AuthenticationFactorFallbackPolicyTest,org.keycloak.protocol.oidc4ac.flow.AuthenticationFactorPlanPlannerTest,org.keycloak.protocol.oidc4ac.flow.AuthenticationFactorPlanStoreTest,org.keycloak.protocol.oidc4ac.providers.NativeAuthenticationMethodDetailsProviderTest' \
  -Dsurefire.failIfNoSpecifiedTests=false test)

OIDC4AC_E2E_CLIENT_URL=http://localhost:5003 \
OIDC4AC_E2E_ISSUER=http://localhost:8186/realms/oidc4ac \
  python3 e2e/http/run.py

docker compose --profile browser-e2e run --build --rm browser-e2e

python3 tests/feature-disabled.py

(cd "$OIDC4AC_LAB_KEYCLOAK_REPO" && ./mvnw -f testsuite/integration-arquillian/tests/pom.xml \
  -Pauth-server-quarkus -pl base -am \
  -Dtest=OIDC4ACAuthenticationContextTest,OIDC4ACCustomProviderIntegrationTest \
  -Dcheckstyle.skip -Dspotless.check.skip=true test)
```

## Keycloak core changes required

- a versioned experimental feature;
- a private authentication-method-details SPI;
- capture of successful current-flow executions;
- immutable snapshot persistence before OIDC protocol completion;
- OIDC discovery/token/UserInfo hooks;
- SSO reauthentication planning; and
- an OIDC-only bridge for terminal browser-flow requirement failures.

No provider replacement is used for discovery or the login protocol.

## Findings and recommendations for the specification

The published draft should incorporate all ten author decisions, especially:

1. a normative recursive grammar and evaluation algorithm;
2. unambiguous top-level and local `essential` semantics;
3. the required `amr_metadata.time` shape and canonical password property
   spelling;
4. precise event scope, SSO, refresh, and later UserInfo semantics;
5. an explicit generic `unmet_authentication_requirements` response rule;
6. disclosure semantics for different requested locations; and
7. finite-domain-only discovery value enumeration.

The draft should also explain that a request language cannot itself guarantee
that an OP has a configured path for every named authentication method. The OP
must define a retry/selection policy and report the event that actually occurs.

## Unresolved engineering work

Remaining engineering work is bounded: a multi-node/offline-token deployment
test. The focused Arquillian suite covers an encrypted JARM
(`RSA-OAEP`/`A256GCM`) error response; other JWE algorithm/key-management
combinations remain deployment-specific. Hardware-specific WebAuthn attestation variants and Admin
Console UI automation are intentionally outside this suite.
The repository also contains a focused `OIDC4ACGrantSnapshotFailoverClusterTest`.
It compiles with the Arquillian suite (667 test sources), but the local
cluster profile could not start its two Quarkus backend adapters: the
load-balancer returned HTTP 503 before the test method ran. This is therefore
an infrastructure-validation gap, not a passing claim for multi-node
failover. The lab is standalone; only generated `.runtime/` and `.build/` state
is ignored by Git.
