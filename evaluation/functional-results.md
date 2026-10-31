# Functional test results

Implementation: Bredstone/keycloak-OIDC4AC 5bd7641d6813828d125932d6c2a2d1d6f91862a7
Laboratory: Bredstone/Keycloak-OIDC4AC-Lab 8a7a597 (master)
Host: Linux 7.0.0-38-generic, executed on 2026-10-29

## Unit tests (OIDC4AC classes in the services module)
- Tests run: 2, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.126 s -- in org.keycloak.authentication.authenticators.oidc4ac.OIDC4ACFactorPlannerAuthenticatorTest
- Tests run: 9, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.023 s -- in org.keycloak.protocol.oidc4ac.AmrDetailsRequestParserTest
- Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.032 s -- in org.keycloak.protocol.oidc4ac.OIDC4ACRealmSettingsTest
- Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.050 s -- in org.keycloak.protocol.oidc4ac.OIDC4ACReauthenticationTest
- Tests run: 6, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.034 s -- in org.keycloak.protocol.oidc4ac.delivery.AmrDetailsProjectionTest
- Tests run: 9, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.011 s -- in org.keycloak.protocol.oidc4ac.disclosure.OIDC4ACDisclosurePolicyTest
- Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.011 s -- in org.keycloak.protocol.oidc4ac.discovery.CustomAuthenticationMethodDetailsProviderTest
- Tests run: 2, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.001 s -- in org.keycloak.protocol.oidc4ac.discovery.OIDC4ACDiscoveryMetadataTest
- Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.006 s -- in org.keycloak.protocol.oidc4ac.error.OIDC4ACAuthenticationFailureBridgeTest
- Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.003 s -- in org.keycloak.protocol.oidc4ac.event.AuthenticationEventSnapshotCodecTest
- Tests run: 4, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.017 s -- in org.keycloak.protocol.oidc4ac.event.AuthenticationEventSnapshotStoreTest
- Tests run: 1, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.001 s -- in org.keycloak.protocol.oidc4ac.flow.AuthenticationFactorFallbackPolicyTest
- Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.007 s -- in org.keycloak.protocol.oidc4ac.flow.AuthenticationFactorPlanPlannerTest
- Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.029 s -- in org.keycloak.protocol.oidc4ac.flow.AuthenticationFactorPlanStoreTest
- Tests run: 7, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.015 s -- in org.keycloak.protocol.oidc4ac.providers.NativeAuthenticationMethodDetailsProviderTest
Total: Tests run: 59, Failures: 0, Errors: 0, Skipped: 0

## Laboratory suites
- PASS  discovery and visual-workbench request handling
- PASS  realm switch gates discovery and authorization
- PASS  structured optional metadata
- PASS  client and redirect validation
- PASS  configured factor flow is visible to the admin API
- PASS  realm and client disclosure policy
- PASS  query, fragment, and form_post error modes
- PASS  JARM error response mode
- PASS  essential password, freshness, and refresh snapshot
- PASS  password credential metadata projection
- PASS  access token excludes amr_details
- PASS  null claim requests the complete event
- PASS  essential claim without expression
- PASS  offline refresh reuses the immutable snapshot
- PASS  old grant survives a later authentication
- PASS  ordinary OIDC login without a claims parameter
- PASS  best-effort unsupported method
- PASS  best-effort value constraint reports actual property
- PASS  identifier values and numeric property bounds
- PASS  essential password and OTP all_of
- PASS  email authenticator sends and verifies an SMTP code
- PASS  repeated method executions preserve timestamps
- PASS  independent delivery projections retain one complete event
- PASS  single-location disclosure
- PASS  one_of branch policy
- PASS  nested all_of / one_of branch policy
- PASS  essential property constraint failure
- PASS  unsupported essential method failure
- PASS  malformed logical expression
- PASS  SSO reauthentication for stronger request
- PASS  essential max_age forces reauthentication
- PASS  best-effort all_of leaf
- PASS  invalid method shape
- PASS  invalid grammar variants
- PASS  ordinary SSO reuse without OIDC4AC claims
- PASS  OIDC4AC SSO reuse preserves execution time
- PASS  concurrent grants retain isolated projections
- PASS  37 end-to-end scenarios
- PASS feature-disabled discovery and authorization regression
- PASS  register passkey and authorize pwd + OTP + pop
- PASS  browser SSO reauthentication for a stronger request
- PASS  unconfigured OTP enrollment resumes with OTP verification
- PASS  authorize OTP + pop without password
- PASS  authorize pwd + pop without OTP
- PASS  authorize reordered pop + pwd without OTP
- PASS  missing passkey failure does not leak enrollment
- PASS  runtime one_of fallback after a retryable pop failure
- PASS  explicit user cancellation returns access_denied
- PASS  9 browser authentication scenarios
