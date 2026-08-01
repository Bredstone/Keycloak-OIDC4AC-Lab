# OIDC4AC Protocol Decision Log

## Scope and status

- Specification repository: `https://github.com/Bredstone/oidc4ac`
- Specification baseline: `fc7c2c5d5155530cd4b71ee44f37cf11e2a578c2`
- Keycloak baseline: `6c73e3027811d9c7b22683edd825e839272e9547`
- Evaluation date: 2026-07-25
- Status: author clarifications received; specification revision pending

This log records decisions supplied by the specification author in response to
the Phase Zero Protocol Clarification Requests (PCRs). They are authoritative
for this experimental Keycloak implementation, but they are not assertions
about the published draft. Every decision that differs from, or resolves a
contradiction in, the draft must be reflected in the specification before it is
presented as published normative behavior.

The implementation and its focused tests are linked below. End-to-end and
laboratory coverage remains tracked in `coverage-matrix.md`; a decision is not
considered fully verified until those rows are complete.

| Decision | Primary implementation | Focused tests |
| --- | --- | --- |
| PD-001 | `AuthenticationEventSnapshotCodec`, `AuthenticationEventSnapshotStore` | `AuthenticationEventSnapshotCodecTest` |
| PD-002 | `NativeAuthenticationMethodDetailsProvider` | `NativeAuthenticationMethodDetailsProviderTest` |
| PD-003 | `AuthenticationMethodDetails`, native provider | `NativeAuthenticationMethodDetailsProviderTest` |
| PD-004 | parser, evaluator, planner | `AmrDetailsRequestParserTest` |
| PD-005 | `AuthenticationRequirementsPlanner` | `AmrDetailsRequestParserTest` |
| PD-006 | `AmrDetailsProjection`, `AmrDetailsDeliveryService` | `AmrDetailsProjectionTest` |
| PD-007 | `AuthenticationEventSnapshotStore`, token delivery | `OIDC4ACReauthenticationTest`, `AuthenticationEventSnapshotCodecTest` |
| PD-008 | `OIDC4ACAuthenticationFailureBridge`, `OIDCLoginProtocol` | `OIDC4ACAuthenticationFailureBridgeTest` |
| PD-009 | `NativeAuthenticationMethodDetailsProvider` | `NativeAuthenticationMethodDetailsProviderTest` |
| PD-010 | `OIDC4ACDiscoveryMetadata` | `OIDC4ACDiscoveryMetadataTest` |

## Decisions

### PD-001 — Required authentication method metadata

- Related PCR: PCR-001
- Published-draft status: contradictory; `amr_metadata` is described as both
  required and optional.
- Author clarification: every AMR Details Object must include `amr_metadata`,
  and `amr_metadata` must always include `time`.
- Keycloak rule: emit only the actual method execution time. Token issuance,
  session creation, credential creation, and credential update times are not
  substitutes.
- Coverage: structural validation, native snapshots, SSO reuse, refresh, and
  UserInfo are exercised by the 37 HTTP scenarios and focused integration
  tests.

### PD-002 — Canonical password derivation property name

- Related PCR: PCR-002
- Published-draft status: contradictory spellings.
- Author clarification: the canonical member name is
  `pwd_derivation_algorithm`; `pwd_derivation_algorithmrithm` is a typo.
- Keycloak rule: emit and advertise only the canonical name. Do not accept or
  emit the typo unless a later compatibility decision explicitly requires it.
- Coverage: canonical-name parsing, serialization, discovery, and token
  projection are exercised by unit, HTTP, and integration tests.

### PD-003 — Method-profile properties

- Related PCR: PCR-003
- Published-draft status: `amr_properties` is optional while profiles designate
  some members as required.
- Author clarification: when `amr_properties` is omitted, no profile property
  is required. When it is present, every unconditionally required property in
  the applicable method profile must be present. An OP that cannot truthfully
  provide every such property must omit the entire `amr_properties` member.
  A trust framework may make optional properties mandatory.
- Keycloak rule: do not infer or synthesize a required property. The native
  browser OTP adapter receives the credential that was actually verified and
  reads only its public credential data; it returns either the complete
  truthful OTP profile or no property object. It never reads or emits a seed,
  generated value, HOTP counter, or credential identifier.
- Coverage: provider disclosure filtering and browser OTP lifecycle are
  exercised by the HTTP/browser suites and native provider tests. WebAuthn
  privacy behavior is covered for virtual CTAP2; hardware variations remain
  intentionally excluded.

### PD-004 — Claim request grammar and evaluation

- Related PCR: PCR-004
- Published-draft status: incomplete grammar and conflicting `essential`
  semantics.
- Author clarification:
  - The top-level `amr_details.essential` controls whether failure to return a
    conforming claim and satisfy its expression fails closed.
  - `amr_details: null` requests the claim when available without prescribing
    authentication. `{"essential": true}` requires a complete, conforming
    claim but does not prescribe a method.
  - A non-essential expression is a best-effort preference. An essential
    expression must be satisfied or the authorization request fails with
    `unmet_authentication_requirements`.
  - `all_of` is Boolean AND and `one_of` is Boolean OR. A `one_of` may be
    satisfied by one or more branches. Branch ordering and attempted-branch
    order have no normative meaning.
  - Internal logical nodes must not contain `essential`.
  - A method leaf matches when its method execution exists and every locally
    essential metadata/property constraint matches. A method is an inclusion
    requirement, never an exclusivity requirement.
  - `essential` within a metadata/property constraint has local leaf scope.
    It requires presence and, when supplied, satisfaction of that constraint;
    it does not propagate through `one_of`.
  - `null` requests a property when available and permitted; absence does not
    prevent a leaf from matching. `value` without local `essential` is a
    best-effort preference. `value` and `values` are mutually exclusive.
  - An essential `max_age` constraint requires a fresh corresponding
    authentication when the existing execution is too old. If it cannot be
    performed, the essential expression is unsatisfied.
  - An expression node contains exactly one of `all_of`, `one_of`, or
    `amr_identifier`; logical arrays are non-empty; unknown operators, invalid
    types, and empty expression objects are `invalid_request`.
- Keycloak rule: model the Claim Request Object separately from the recursive
  expression. A planner may choose any viable branch, but must evaluate the
  immutable resulting event using the rules above.
- Coverage: parser negative cases, nested Boolean expressions, claim/local
  essentiality, fresh authentication, and complete-event preservation are
  exercised by unit, HTTP, and browser scenarios.

### PD-005 — Best-effort constraints

- Related PCR: PCR-005
- Published-draft status: it says unsatisfied descriptive constraints must be
  ignored, which conflicts with the intended request model.
- Author clarification: the OP must attempt every requested constraint on a
  best-effort basis. Constraints must not simply be ignored. Reapplication of
  a method is an OP decision for a non-essential constraint; any returned
  `amr_details` value must describe what actually occurred. A local essential
  constraint controls leaf matching as specified by PD-004.
- Keycloak rule: preserve requested constraints for planning and evaluation;
  never write requested values into the event snapshot.
- Coverage: HTTP scenarios exercise `null`, `value`, `values`, `min`, `max`,
  and `max_age`, including best-effort and locally essential constraints.

### PD-006 — Multiple delivery locations and disclosure

- Related PCR: PCR-006
- Published-draft status: different delivery-location requests and
  "semantically equivalent" content were unspecified.
- Author clarification: all essential expressions requested for ID Token and
  UserInfo are combined conjunctively for one authorization transaction.
  Non-essential expressions remain best-effort preferences. An unsatisfied
  combined essential requirement returns `unmet_authentication_requirements`.
  The resulting Authentication Context is one immutable snapshot used for the
  ID Token, access-token-bound UserInfo response, and later tokens derived
  from the same authorization grant.

  Disclosure is separately evaluated for each requested location. The two
  locations may contain different projections of the same snapshot according
  to their requests and disclosure policy, but each projection retains the
  complete set of executions relied upon by the authorization, including each
  execution's identifier and mandatory time. "Semantically equivalent" means
  that the execution set and overlapping values refer to the same event; it
  does not require identical optional metadata or properties. By default, a
  location receives only the optional fields it requested. Later UserInfo
  responses must not reconstruct mutable state or disclose additional history.
- Keycloak rule: apply any realm/client disclosure filter before essential
  expression evaluation. If that filter prevents an essential request from
  being represented and returned, fail with
  `unmet_authentication_requirements`; it must never silently remove an
  execution from the event.
- Keycloak rule: separate requirement combination from projection and
  serialization. Do not put `amr_details` in access tokens unless separately
  authorized.
- Coverage: HTTP and Arquillian scenarios exercise ID Token-only, UserInfo-only,
  combined differing requests, policy-filtered projections, and later UserInfo.

### PD-007 — Authentication Event scope and lifetime

- Related PCR: PCR-007
- Published-draft status: no event boundary or token-lifetime rule.
- Author clarification: `amr_details` represents the complete Authentication
  Event relied upon by the corresponding authorization. The OP should preserve
  an immutable snapshot associated with that grant. SSO reuse preserves each
  reused method's original execution time. Refresh-derived tokens and UserInfo
  use that same snapshot, never mutable user-session state. The snapshot is
  not the user's complete authentication history.
- Keycloak rule: do not rebuild details from Keycloak's merged
  completed-authenticator user-session note after authorization.
- Keycloak rule: do not use the authenticated client-session notes as the
  authorization-grant carrier. They are mutable and shared by concurrent tabs.
  Store the event and canonical claims request server-side under an opaque,
  random grant handle bound to the authorization code, bearer token, and
  refresh token. The handle contains no authentication details and is never
  delivered as `amr_details`.
- Coverage: HTTP and Arquillian scenarios exercise SSO reuse, repeated
  execution, repeated refresh, UserInfo after new authentication activity,
  timestamp preservation, and parallel authorizations for one user/client.

### PD-008 — Authentication requirement failure response

- Related PCR: PCR-008
- Published-draft status: the draft requires `access_denied` and suggests
  identifying the unsatisfied expression.
- Author clarification: an unsatisfied essential `amr_details` request or
  expression returns `unmet_authentication_requirements`. The public response
  must not distinguish unenrolled, unsupported, unavailable, verification
  failure, or essential-property-constraint failure. `access_denied` should be
  reserved for End-User cancellation or refusal.
- Implementation deviation: this supersedes the published draft's
  `access_denied` instruction and introduces a protocol-specific error value.
  It must remain labeled as an author clarification until the draft is revised.
- Keycloak rule: create a focused, OIDC-only error-propagation hook after
  client and redirect URI validation. The public description must be generic.
- Coverage: HTTP and browser scenarios exercise valid/invalid redirect URI
  handling, state preservation, cancellation, unsupported/unenrolled methods,
  and no-enrollment leakage. Hardware-specific verification variants remain
  intentionally excluded.

### PD-009 — WebAuthn and passkeys

- Related PCR: PCR-009
- Published-draft status: no WebAuthn/passkey mapping.
- Author clarification: a successfully verified WebAuthn assertion may be
  represented as `pop`. It must not be represented as `hwk` or `swk` without
  trustworthy evidence of the respective key protection. Backup eligibility,
  backup state, authenticator attachment, and an unattested AAGUID are not
  sufficient evidence alone. Credential identifiers should be omitted unless
  necessary; when disclosed, they must be opaque and pairwise to the RP.
- Keycloak rule: advertise only `pop` for native WebAuthn/passkeys unless a
  separately approved evidence and disclosure policy exists. Do not emit an
  AAGUID, credential ID, public key, or attestation material by default.
- Required future coverage: WebAuthn; passwordless WebAuthn; no `hwk`/`swk`
  inference; pairwise identifier policy; no sensitive credential disclosure.

### PD-010 — Discovery capability value lists

- Related PCR: PCR-010
- Published-draft status: a value list appears mandatory for every advertised
  property despite being a JSON string array.
- Author clarification: `<property>_values_supported` is required only for a
  finite, closed string vocabulary. Numeric values, booleans, timestamps,
  objects, identifiers, and open or unbounded domains are not enumerated; the
  applicable method profile defines their JSON types and semantics. Advertising
  a property means the OP understands and may produce it when applicable, not
  that it is available for every user, event, or requested value.
- Keycloak rule: advertise only real enabled-provider capabilities. Do not
  publish a value list for numeric, temporal, or open-domain properties.
- Coverage: disabled/enabled discovery, finite string values, numeric bounds,
  and timestamp behavior are exercised by the HTTP and integration suites.

### PD-011 — Optional authentication-event metadata

- Keycloak extension decision: native password, OTP, and WebAuthn adapters may
  provide `amr_metadata.iss` when the current request context supplies it.
  `iss` is the realm issuer derived from Keycloak's configured frontend URI.
  When Keycloak supplies a client network address, native adapters represent
  it as the protocol-defined object
  `{ "location": { "ip_address": "..." } }`; they do not infer geospatial
  coordinates or postal address fields.
- Keycloak rule: issuer metadata remains optional, is advertised dynamically,
  and is subject to the realm/client per-field disclosure modes. Missing
  context never makes authentication fail. Trust-framework, assurance-level,
  and location metadata require an evidence-bearing provider with a
  protocol-conformant representation and are not inferred by native adapters.
- Remaining deployment-specific coverage: geospatial/address enrichment,
  assurance, and trust-framework evidence providers. Native adapters correctly
  stop at the safe issuer/IP subset; a custom provider can supply richer
  evidence through the private SPI.

## Follow-up required before implementation

The published draft must be revised to incorporate these clarifications. Until
then, generated documentation, discovery, protocol reports, and tests must
identify the behavior as an author clarification rather than published-draft
semantics.
