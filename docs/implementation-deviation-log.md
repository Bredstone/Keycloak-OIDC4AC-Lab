# OIDC4AC Implementation Deviation Log

- Keycloak baseline: `6c73e3027811d9c7b22683edd825e839272e9547`
- Specification baseline: `fc7c2c5d5155530cd4b71ee44f37cf11e2a578c2`
- Date: 2026-07-29

This log distinguishes author-approved clarifications from Keycloak-specific
choices and limitations. It must not be read as an edit to the published draft.

| ID | Status | Difference or limitation | Impact |
| --- | --- | --- | --- |
| D-001 | Author clarification | `unmet_authentication_requirements` replaces the draft's `access_denied` instruction for an unsatisfied essential request (PD-008). | The draft must be revised before this is advertised as published behavior. Public descriptions remain generic. |
| D-002 | Resolved opt-in browser planning | The default policy still re-runs the configured browser flow. A realm can opt into the OIDC4AC factor planner, which selects an ordered subset of configured child factor subflows, deterministically chooses feasible `one_of` branches, and falls through to the next preplanned branch on a safe terminal method failure. | The RP cannot invoke a provider or control order. Explicit cancellation remains `access_denied`. The disposable browser lab covers the configured planner path; other realm flow layouts remain deployment-specific. See `browser-factor-planning.md`. |
| D-003 | Resolved native handoff | After a successful browser OTP verification, the private adapter receives the selected credential ID from the native authentication event and reads only its public credential data. It emits a complete truthful OTP profile when available. | `otp_length`, `otp_algorithm`, `otp_format`, `otp_delivery_method`, and (for TOTP) `otp_time_to_live` are available. OTP seeds, generated values, HOTP counters, and credential identifiers are neither emitted nor serialized. |
| D-004 | Revised author clarification | `amr_details` always represents the complete Authentication Event relied upon for the authorization. Expression-based delivery retains every execution with its mandatory `amr_identifier` and `amr_metadata.time`; expressions select only optional metadata and properties at each location. | ID Token and UserInfo may minimize optional fields differently, but must represent the same complete execution set. A stricter realm/client disclosure policy must run before essential-expression evaluation and cause `unmet_authentication_requirements` when it prevents an essential request from being represented and returned. |
| D-005 | Resolved grant isolation | Each requested `amr_details` authorization receives an immutable, server-side snapshot and canonical `claims` request keyed by a random grant handle. The handle is bound privately to the authorization code, access token, and refresh token; it is never an `amr_details` value. | Concurrent grants for one client/user session cannot overwrite each other's event or delivery request. ID Token, access-token-bound UserInfo, and refresh-derived tokens load only the handle-bound snapshot. |
| D-006 | Resolved for the lab authorization endpoint | The OIDC-only browser-flow bridge is unit-tested and exercised through the real authorization-code endpoint for malformed requests, unsupported essential methods, essential constraint failures, invalid client/redirect validation, explicit consent cancellation, state-preserving query/fragment/form-post response modes, signed JARM (`response_mode=jwt`), and an encrypted RSA-OAEP/A256GCM JARM response. | Public essential failures are generic `unmet_authentication_requirements`; other JWE algorithm/key-management combinations remain deployment-specific. |
| D-007 | Realm-scoped experimental switch | OIDC4AC is enabled for existing realms unless the `oidc4ac.enabled` realm attribute is explicitly set to `false`. The Admin Console exposes this switch under Realm settings → General; the OIDC4AC policy tab is shown only while enabled. | Disabling removes OIDC4AC discovery metadata and skips request validation, planning, event capture, and claim delivery while preserving the configured flow and disclosure policy. |
| D-008 | Optional metadata safe subset | Native methods emit `iss` when request context data is available and represent the request-context network origin as the protocol-defined structured `location` object (`{ "ip_address": "..." }`) when a client address is available. | Location is optional and policy-filtered. Native methods advertise only `ip_address`; geospatial/address fields, `trust_framework`, and `assurance_level` require an evidence-bearing custom provider. |

## Not deviations

- `amr_metadata.time` is always emitted, per PD-001.
- `pwd_derivation_algorithm` is the only accepted/emitted spelling, per PD-002.
- WebAuthn/passwordless WebAuthn emits `pop` only and never emits a credential
  identifier, AAGUID, public key, attestation, `hwk`, or `swk`, per PD-009.
- Discovery value lists are emitted only for finite closed string vocabularies,
  per PD-010.
