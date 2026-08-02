# Protocol alignment

This document is the bridge between the protocol and this implementation. The
normative source used for the current lab is the
[OIDC4AC protocol](https://bredstone.github.io/oidc4ac/) maintained by the
[main source repository](https://github.com/Bredstone/oidc4ac).

## The wire model

OIDC4AC is carried inside the normal OIDC `claims` parameter. A request may
contain `id_token.amr_details`, `userinfo.amr_details`, or both. The response
claim is an array of method executions:

```json
{
  "amr_details": [
    {
      "amr_identifier": "otp",
      "amr_metadata": {
        "time": "2026-08-02T12:34:56Z"
      },
      "amr_properties": {
        "otp_algorithm": "TOTP"
      }
    }
  ]
}
```

For every returned execution, `amr_identifier` and `amr_metadata.time` are
required. `amr_metadata` is required as an object even when no optional
metadata is available. `amr_properties` is optional; if emitted, the provider
must be able to provide every unconditionally required property of the
applicable method profile. The OP must omit the entire properties object
rather than inventing or partially filling it.

Optional metadata includes `iss`, `trust_framework`, `assurance_level`, and a
structured `location` object. A location is not a string shortcut; it may use
the protocol's defined members such as `formatted`, `street_address`,
`locality`, `region`, `postal_code`, `country`, `ip_address`, `latitude`,
`longitude`, and `precision`. For example:

```json
{
  "amr_metadata": {
    "time": "2026-08-02T12:34:56Z",
    "iss": "https://authenticator.example",
    "location": {
      "ip_address": "192.0.2.10",
      "country": "BR"
    }
  }
}
```

The lab emits only metadata for which the current provider and request
context have evidence. It does not infer a country or geospatial precision
from an IP address.

## Normative behavior mapped to the lab

| Protocol rule | Keycloak behavior | Lab evidence |
| --- | --- | --- |
| `amr_details` is an OIDC claim | OIDC authorization, token, UserInfo, and Discovery hooks add the claim without replacing native OIDC providers | HTTP discovery and authorization suites |
| Request support is advertised separately from informational claim support | `claims_supported` and `amr_details_request_supported` are gated by the realm feature/planner state | `./dev.sh verify`, disabled-profile suite |
| Recursive `all_of`/`one_of` grammar | Parser validates one operator per expression, non-empty arrays, local constraints, and nested groups | Unit and HTTP malformed/nested scenarios |
| Top-level `essential` is fail-closed; omitted/false is best effort | Planner/evaluator combines essential requirements and returns the generic protocol error when unsatisfied | Essential, unsupported, and property-constraint scenarios |
| Nested groups do not carry `essential` | Parser rejects invalid nested essential placement | Parser negative tests |
| `null`, `value`, `values`, `min`, `max`, and `max_age` have distinct semantics | Evaluator compares requested constraints to observed values and never writes requested values into the event | Constraint and fresh-authentication scenarios |
| `one_of` is OR, not an ordered preference | Planner can select a feasible branch and retry a preplanned branch after a retryable failure | Browser fallback scenarios |
| Essential requirements from ID Token and UserInfo combine conjunctively | One authorization requirement is evaluated before independent projections | Combined-location HTTP scenarios |
| The event contains every relied-upon execution | Expression filtering never removes a method from the immutable snapshot; only optional fields are projected | Complete-event and projection scenarios |
| SSO, refresh, and later UserInfo reuse the grant snapshot | An opaque grant handle selects immutable event data; mutable session history is not reconstructed | Refresh, old-grant, SSO, and concurrency scenarios |
| Disclosure policy is applied before essential representation evaluation | Realm/client policy can cause a generic unmet-requirements error, never an incomplete essential response | Realm/client policy scenarios |
| Unsupported essential requests have a generic failure | Keycloak does not reveal enrollment, availability, verification, or property causes | HTTP/browser privacy scenarios |
| WebAuthn maps conservatively | Verified assertions are represented as `pop`; `hwk`/`swk` are not inferred from attachment or backup flags | Virtual CTAP2 browser suite |
| Discovery enumerates only finite string domains | Open numeric, timestamp, object, and identifier domains are type-described rather than listed | Discovery smoke checks |

## Discovery contract

The implementation may advertise:

- `amr_details` in `claims_supported` for informational disclosure;
- `amr_details_request_supported` when request processing is available;
- `amr_identifiers_supported`;
- `<amr>_properties_supported` and finite `<property>_values_supported`;
- `trust_framework_values_supported` and
  `assurance_level_values_supported` when a provider has evidence and policy;
  and
- `location_types_supported` for supported structured location members.

If request support is absent or false, an OP must not fail ordinary OIDC
authorization because an RP supplied method expressions. It may ignore the
expression and continue normal processing; informational claim behavior is a
separate decision.

The lab's built-in providers advertise `pwd`, `otp`, `pop`, and the disposable
`email` method. It deliberately does not advertise `trust_framework`,
`assurance_level`, or additional location semantics because the fixture has no
independent evidence for those claims.

## Disclosure and privacy

The complete Authentication Event is preserved for the grant. An ID Token and
UserInfo response may expose different optional fields, but overlapping data
must refer to the same event and values. Mandatory identifiers and execution
times remain in every projection. A later UserInfo response is not allowed to
discover extra history merely because the user authenticated again later.

Realm/client disclosure policy is evaluated before essential request
satisfaction. If policy prevents a required field or execution from being
represented, the authorization fails with
`unmet_authentication_requirements`; the OP must not silently return a partial
event.

## Implementation versus profile completeness

The protocol method profiles define which properties are required or optional
when an OP emits them. A lab provider may emit a conservative subset of safe
properties, subject to the applicable profile and disclosure policy. Discovery
means “understands and may produce”, not “available for every user or every
execution”. A custom provider must provide truthful evidence, keep secrets and
replayable artifacts out of the claim, and align its Discovery metadata with
the objects it can actually return.

## Known validation boundaries

The lab does not certify every Keycloak deployment, storage backend, hardware
authenticator, or JWE configuration. Multi-node/offline-token failover and
additional encrypted-JARM combinations remain deployment validation work.
