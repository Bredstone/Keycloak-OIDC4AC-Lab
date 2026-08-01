# OIDC4AC Dynamic Browser-Factor Planning

## Status

This is an experimental, opt-in browser-flow extension for
`oidc4ac:v1`. It does not alter a realm's normal browser flow or create realm
flow models from an RP request.

When an authorization does not request `amr_details`, the planner does not
store a factor plan. The configured container then follows its ordinary
Keycloak alternative-flow behavior. This lets the same browser flow service
Account Console and other non-OIDC4AC logins; in the lab, the first alternative
is the password factor.

The extension creates one immutable, server-side plan in the authentication
session. The plan contains only IDs of factor subflows that a realm
administrator has already configured. The plan is an instruction to run a
subset of that catalogue for one authorization; it is never returned to the
RP or browser.

## Flow configuration

Put the **OIDC4AC factor planner** and its required factor-container in the
same interactive alternative subflow. Configure the planner's
`factor_flow_alias` with the container's alias. Keep the normal browser-cookie
authenticator as a sibling *alternative of that subflow*, rather than beside
the planner/container: Keycloak ignores alternatives when they share a level
with required executions.

The factor container must be required. Each of its factor children must be an
alternative *subflow*, with an alias of `oidc4ac:<amr_identifier>`. The content
of each child uses normal Keycloak authenticators and must be required within
that child subflow.

For example:

```text
Browser flow
  Cookie                                            ALTERNATIVE
  OIDC4AC browser forms                            ALTERNATIVE subflow
    OIDC4AC factor planner                         REQUIRED
        factor_flow_alias = oidc4ac-factors
    oidc4ac-factors                                REQUIRED
      oidc4ac:pwd                                  ALTERNATIVE subflow
        Username Password Form                     REQUIRED
      oidc4ac:pop                                  ALTERNATIVE subflow
        WebAuthn Authenticator                     REQUIRED
      oidc4ac:otp                                  ALTERNATIVE subflow
        OTP Form                                   REQUIRED
      oidc4ac:email                                ALTERNATIVE subflow
        Custom Email Code Authenticator            REQUIRED
```

The planner must precede the container, and the container must be its direct
sibling. The outer cookie branch preserves SSO and Account Console silent-login
checks. A factor that requires an identified user also needs the realm to
establish that identity first, through that SSO cookie or an ordinary preceding
identity step inside the interactive branch.

An `email` child becomes eligible only when an installed
`AuthenticationMethodDetailsProvider` advertises `email` and describes a
successful email execution. The exact same rule applies to every custom method.

## Request behavior

The planner parses both ID Token and UserInfo requests and creates a plan from
the combined requirements:

- Every leaf in `all_of` is selected.
- Exactly one feasible branch is chosen for each `one_of`.
- A binding's realm execution priority determines plan order; array order in
  an RP's request has no control effect.
- If the selected branch ends with a retryable method failure, the container
  advances to the next preplanned branch. Explicit End-User cancellation never
  falls through and remains `access_denied`.
- An essential property whose name is not advertised for a selected method is
  unplannable and fails through the generic
  `unmet_authentication_requirements` path.
- Unsupported non-essential expressions are omitted from the plan and remain
  best effort.

The planner can therefore select four or more factors. For an essential
`all_of(pwd, otp, pop, email)`, the container executes the four configured
subflows in realm-priority order. It does not mutate their requirements or
persist a new realm flow.

The final OIDC4AC evaluator remains authoritative. A plan is never proof that
a method ran: only the normal authenticators can succeed, and the existing
recorder snapshots their actual safe details. If a planned factor fails, is
unavailable, or cannot truthfully provide an essential property constraint, an
essential request results in the generic failure response rather than a partial
authentication claim.

If a branch partially succeeds before a later factor fails, those successful
executions remain part of the complete Authentication Event when a later branch
succeeds. The fallback mechanism does not erase or reconstruct authentication
history; it only changes the next configured factor to try.

## Current boundaries

- The planner chooses from configured browser subflows only; it does not route
  into arbitrary provider IDs or dynamically install authenticators.
- One authorization currently supports one configured OIDC4AC factor
  container.
- The current branch policy is deterministic realm priority. It retries only
  branches present in the original immutable plan; it does not discover or
  enable a new method at runtime.
- Capability metadata is a feasibility hint, not an enrollment guarantee.
  Runtime verification and final event evaluation remain required.
- The browser factor container is intentionally separate from direct grant and
  other non-browser authentication flows.

## Admin Console configuration

With `oidc4ac:v1` enabled, the Admin Console exposes an **OIDC4AC** sub-tab
under **Realm settings → OIDC4AC** for the realm enable switch and disclosure
default. This page does not create or configure an authentication flow. It reports whether
an enabled `oidc4ac-factor-planner` execution is present, while the planner and
its factor flow are configured in the normal **Authentication → Flows** UI.
When no planner is enabled, discovery still advertises the informational
`amr_details` claim but sets `amr_details_request_supported` to `false`.

The disclosure editor consumes the realm's OIDC discovery document. It creates
one tab per advertised `amr_identifier`, lists that method's supported
properties and finite value vocabularies, and includes custom metadata names
advertised by an installed authentication-method-details provider. Realm
defaults can allow all, allow selected optional fields, or deny optional
fields. An OIDC4AC tab on each OpenID Connect client provides an independent
inherit/selected/none override, so administrators can set disclosure without
typing client IDs or property paths.
