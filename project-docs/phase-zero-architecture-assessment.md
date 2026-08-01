# OIDC4AC Phase Zero Architecture Assessment

- Keycloak baseline: `6c73e3027811d9c7b22683edd825e839272e9547`
- Specification baseline: `fc7c2c5d5155530cd4b71ee44f37cf11e2a578c2`
- Evaluation date: 2026-07-25
- Status: Phase Zero complete after author clarifications PD-001 through PD-010

## Result

OIDC4AC is implementable as an experimental, feature-gated Keycloak extension.
The published early draft was not independently implementable without the ten
author clarifications recorded in `protocol-decision-log.md`. Those decisions,
not the unresolved published wording, are the Phase One protocol baseline.

ADR-001 records the selected module placement and SPI boundary.

## Keycloak integration assessment

| Area | Existing Keycloak mechanism | Phase One approach |
| --- | --- | --- |
| Feature lifecycle | `Profile.Feature` supports versioned experimental features | Add `OIDC4AC`, exposed as `oidc4ac:v1`, disabled by default. |
| Authorization validation | `AuthorizationEndpointChecker` invokes registered `AuthorizationEndpointCheckProvider`s after client and redirect validation | Validate the OIDC4AC subset of `claims` with a feature-gated add-on. |
| Request persistence | `AuthorizationEndpoint` copies `claims` to the authentication session and later client session | Store a validated, canonical request and immutable event snapshot under a grant-specific server-side handle; never use the mutable client session or merged user-session completed-authenticator note for delivery. |
| Browser authentication | Native authenticators report successful executions into the flow and `AuthenticationProcessor` owns browser errors | Add a narrow current-transaction recorder and OIDC-safe requirement-failure bridge. Do not replace `LoginProtocol`. |
| Tokens and UserInfo | OIDC protocol mappers are applied to ID Token and UserInfo and receive the authenticated client session | Use an opaque access-token grant handle to project the one stored snapshot separately for each requested delivery location. Do not add `amr_details` to access tokens. |
| Refresh | Refreshed ID Tokens are built from the authenticated client session | Restore the grant handle from the verified refresh token and reuse that snapshot, not current session state. |
| Discovery | `OIDCWellKnownProvider` constructs native metadata | Add a small feature-gated augmentation hook; do not replace the provider. |
| Password and OTP | Native credential authenticators own verification | Adapters emit only safe method facts after success; no hashes, salts, OTP seed, value, or HOTP counter. |
| WebAuthn | Native WebAuthn authenticators own assertion verification | Describe verified assertions as `pop` only; do not infer `hwk` or `swk`, and omit identifiers and attestation material. |

## External proof-of-concept classification

| Component | Classification | Reason |
| --- | --- | --- |
| Pure request parser/evaluator scenarios | Reusable after adaptation | They must adopt PD-004 and PD-005 grammar and evaluation rules. |
| Terraform realm/client configuration | Reusable after adaptation | It remains the laboratory source of truth but must target the fork build. |
| Docker Compose, development script, and Flask client | Reusable after adaptation | They remain useful end-to-end tooling but must not encode OP semantics. |
| Custom OIDC well-known provider | Superseded | Native discovery must be augmented rather than replaced. |
| Completed-authenticator session-note parsing | Superseded | It is mutable session history, not the immutable authorization event required by PD-006 and PD-007. |
| External protocol mapper wiring | Superseded | Claim delivery must be native and tied to the immutable grant snapshot. |
| Browser-flow error workaround | Superseded | The fork needs a focused OIDC authorization-response path. |

## Phase One delivery order

1. Feature registration, private SPI, pure request model/parser/evaluator, and
   unit tests.
2. A feature-gated authorization validation hook and a canonical request
   persistence boundary.
3. Current-authorization event capture and immutable snapshot persistence.
4. ID Token and UserInfo projections, refresh reuse, and discovery
   augmentation.
5. Native password, OTP, and WebAuthn adapters plus OIDC-only failure
   propagation.
6. Keycloak integration tests, laboratory migration, coverage matrix, security
   review, and protocol validation report.

## Initial constraints

- The feature remains experimental and disabled by default.
- Every behavior based on PD-001 through PD-010 is labelled as an author
  clarification until the published draft is revised.
- No token or discovery behavior changes when the feature is disabled.
- The implementation records the event actually relied upon for one
  authorization; it does not reconstruct account-wide history.
- The snapshot and all SPI values are secret-free.
