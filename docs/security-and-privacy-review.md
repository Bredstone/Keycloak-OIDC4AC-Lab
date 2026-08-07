# OIDC4AC Security and Privacy Review

## Scope

This review covers the OIDC4AC support provided by the lab's Keycloak instance
against the [OIDC4AC protocol](https://bredstone.github.io/oidc4ac/) from the
[main source repository](https://github.com/Bredstone/oidc4ac) and the
corresponding Keycloak behavior. This review does not claim production
hardening or multi-node/persistent-grant validation.

The optional hosted instance deliberately exposes its smtp4dev web inbox
without a login so users can inspect the example email factor. It is a
disposable sink for test messages only; no real email or personal data belongs
there.

## Data disclosure

The private SPI accepts JSON-compatible, deep-copied values only. Native
providers may emit the method identifier, the actual execution time, and safe
properties that they can establish truthfully.

The implementation never emits password hashes or salts, OTP seeds, generated
OTP values, HOTP counters, WebAuthn credential IDs, AAGUIDs, public keys,
attestation, or private/replayable authenticator material. WebAuthn and
passkeys are represented only as `pop`; attachment, backup state, backup
eligibility, and an unattested AAGUID are not used to infer `hwk` or `swk`.

For a verified browser OTP execution, the selected credential is used only
inside the private adapter to read public credential data. The adapter emits
the OTP mode, length, numeric format, app delivery method, and TOTP period
when applicable; it does not read the secret data or serialize the credential
identifier.

## Correlation and minimization

The snapshot carries no credential identifier. Every delivery location retains
the complete set of method executions relied upon by the authorization, with
each method's identifier and mandatory execution `time`. A constrained
location minimizes only optional metadata and properties; a `null` request
receives all available optional fields. ID Token and UserInfo may therefore
differ while referring to the same immutable execution set. This means method
identifiers and timestamps remain meaningful authentication-context disclosure
and must be requested only when needed.

## Error handling and enrollment disclosure

Malformed OIDC4AC requests are `invalid_request` after normal client and
redirect-URI validation. An unsatisfied essential requirement uses the
author-approved `unmet_authentication_requirements` with one generic
description. The implementation does not disclose whether the cause was no
enrollment, an unsupported method, unavailable infrastructure, verification
failure, or a property constraint. User cancellation stays on Keycloak's normal
`access_denied` path.

## SSO, replay, and lifetime

The event is serialized at successful authentication and reused for SSO,
ID Token, UserInfo, and refresh paths; its method timestamps are never replaced
by session or token issuance time. Each authorization that requests
`amr_details` receives a separate server-side snapshot and canonical claims
request. A random, opaque handle in the verified authorization code, access
token, or refresh token selects that record; the handle carries no event data
and is not delivered as `amr_details`. If an SSO event does not satisfy a
request, the configured browser flow is retried.

## Outstanding security work

- Exercise additional encrypted-JARM algorithm/key-management combinations
  beyond the RSA-OAEP/A256GCM path covered by the focused Arquillian test
  (signed `response_mode=jwt` is covered by the HTTP lab).
- Validate grant lifetime and offline-token refresh across a real multi-node or
  persistent-session deployment.
