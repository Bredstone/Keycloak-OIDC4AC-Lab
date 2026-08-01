# ADR-001: OIDC4AC Module Placement and Experimental SPI

- Status: accepted for Phase One design
- Date: 2026-07-25
- Keycloak baseline: `6c73e3027811d9c7b22683edd825e839272e9547`
- Protocol baseline: `fc7c2c5d5155530cd4b71ee44f37cf11e2a578c2`, plus the
  author clarifications recorded in `protocol-decision-log.md`

## Context

OIDC4AC needs a pure request/response model, a method-details extension
contract, native password/OTP/WebAuthn adapters, OIDC authorization and token
integration, discovery metadata, and a browser-flow failure path. The current
external PoC instead overrides OIDC discovery, parses a private completed-
authenticator session note, and uses an external protocol mapper and browser
authenticators. Those patterns are not suitable for an in-tree experimental
feature.

Keycloak 26.7.0 has this relevant dependency direction:

```text
common ──> server-spi <── server-spi-private <── services
                                               |
                                OIDC endpoints and native authenticators
```

`services` already depends on both SPI artifacts and on Jackson. The
`server-spi` artifact is a supported public API; `server-spi-private` is where
Keycloak keeps internal and evolving extension contracts. Existing OIDC4VC
uses an in-tree authorization-endpoint check provider, and `Profile.Feature`
generates a versioned feature key from an enum entry ending in `_V1`.

## Decision

1. Register `OIDC4AC` as a versioned `Type.EXPERIMENTAL` feature in
   `common`.

   Its user-facing key is `oidc4ac:v1`. Experimental features are disabled by
   default in Keycloak 26.7.0, satisfying the required default. Every OIDC4AC
   request, event capture, token claim, error, and discovery customization is
   guarded by this feature.

2. Keep the OIDC4AC protocol model and integration in `services`.

   `org.keycloak.protocol.oidc4ac` will contain immutable request, expression,
   constraint, event-snapshot, projection, discovery, parser, and evaluator
   types. These classes must not access credential secrets. They are placed in
   `services` because the parser uses Keycloak's JSON support and the OIDC
   authorization, token, UserInfo, and discovery code already belongs there.
   Package separation, not a new Maven artifact, keeps the pure model easy to
   unit-test without adding a dependency cycle or a premature standalone API.

3. Add the authentication-method-details SPI to `server-spi-private`.

   The experimental SPI will expose provider/factory contracts and immutable,
   secret-free capability, execution, and detail-result objects. Providers can
   report supported AMR identifiers, disclose only verified properties, return
   explicit unavailable/unknown outcomes, and resolve an actual execution
   timestamp. Native adapters live in `services`; third-party experimental
   providers may compile against the private SPI for the exact Keycloak
   version. The SPI is deliberately not in `server-spi` until its protocol and
   provider lifecycle have stabilized.

4. Add focused integration hooks rather than replacing providers.

   - An OIDC authorization-endpoint check validates OIDC4AC request structure
     after client and redirect-URI validation.
   - A small authentication-flow recorder captures supported successful native
     executions for the current authorization transaction only. It must not
     rebuild history from `authenticators-completed`.
   - A snapshot service writes one immutable Authentication Event snapshot and
     canonical claims request to server-side grant storage before protocol
     completion. An opaque handle binds the authorization code, access token,
     and refresh token to that record, so ID Token, refreshed ID Token, and
     UserInfo do not read the shared authenticated-client session state.
   - A discovery customizer augments Keycloak's native OIDC discovery
     representation. It must not replace `OIDCWellKnownProvider`.
   - A focused OIDC browser-flow failure bridge produces the approved
     `unmet_authentication_requirements` authorization response only after
     normal client and redirect-URI validation.

5. Implement password, OTP, and WebAuthn adapters through the SPI.

   Native authenticators remain the sole verifiers. The adapters only describe
   successful executions and safe capabilities. The initial WebAuthn mapping
   is `pop`; it must not infer `hwk` or `swk`.

## Dependency and API implications

```text
server-spi-private: OIDC4AC method-details SPI and secret-free value objects
          ^
          |
services: parser/model + OIDC integration + native adapters + focused hooks
          |
          +--> existing browser authenticators, token manager, discovery
```

No OIDC4AC dependency may point from `server-spi-private` back to `services`.
The private SPI must not expose password hashes, OTP secrets/counters, WebAuthn
credential IDs, private material, public keys, or mutable session state. A
future promotion to `server-spi` requires a separate compatibility review.

## Rejected alternatives

- **External provider JAR only:** cannot add the required focused core hooks;
  it requires a discovery replacement and private session-note parsing.
- **Replace `OIDCWellKnownProvider`:** duplicates native discovery assembly and
  is upgrade-sensitive.
- **Replace `OIDCLoginProtocol`:** is disproportionate for one browser-flow
  error path and risks unrelated OIDC regressions.
- **Put the experimental SPI in `server-spi`:** makes an unintended stable
  public compatibility commitment before the protocol has stabilized.
- **Create a new Maven module now:** adds build and distribution surface without
  resolving a dependency problem; reconsider only if the pure model becomes
  reusable beyond `services`.

## Upstream review path

Reviewers can evaluate the change in separable layers:

1. feature registration and private SPI;
2. pure parser/model/evaluator tests;
3. generic focused hooks for event capture, discovery customization, and OIDC
   flow failure propagation;
4. OIDC4AC integration and native adapters;
5. end-to-end tests and laboratory migration.

The feature must leave existing OIDC behavior, metadata, tokens, and browser
errors unchanged when `oidc4ac:v1` is disabled.
