# Documentation guide

Start with the [README](../README.md) to understand the lab and start its
services. This page points you to the next document based on your goal.

## Choose a path

| You want to… | Read |
| --- | --- |
| Understand OIDC4AC and start the lab | [README](../README.md), then [OIDC4AC integration in Keycloak](keycloak-oidc4ac.md) |
| Run a first authorization and inspect tokens | [Using the test client](test-client.md) |
| Learn the request format and try scenarios | [Usage flows](usage-flows.md) |
| Configure a realm, client, ports, or variables | [Configuration reference](configuration-reference.md) and [Browser factor planning](browser-factor-planning.md) |
| Create a custom authentication method | [Creating a custom authentication method with the SPI](custom-authentication-spi.md) and the provider under `../providers/` |
| Understand the protocol-to-implementation relationship | [Protocol alignment](protocol-alignment.md) |
| Review security and privacy | [Security and privacy review](security-and-privacy-review.md) |
| Use the hosted reviewer deployment | [Hosted demonstration](hosted-demo.md) |
| Resolve a local issue | [Troubleshooting](troubleshooting.md) |

## Protocol source

The normative reference is the [OIDC4AC protocol](https://bredstone.github.io/oidc4ac/),
maintained in the [protocol source repository](https://github.com/Bredstone/oidc4ac).
It defines the grammar, representation, Discovery, disclosure rules, and
examples. The documents in this repository explain how that reference is
applied in the lab; they are not an alternative specification.

## Terms used in the guides

- **OP** — OpenID Provider; Keycloak in this lab.
- **RP** — Relying Party; the test client in this lab.
- **Authentication method** — for example, `pwd`, `otp`, `pop`, or `email`.
- **Execution** — one successful use of a method during an authorization.
- **Authentication event** — the complete set of relied-upon executions.
- **Snapshot** — an immutable representation of the event bound to an authorization.
- **Requirement** — an expression sent by the RP for the expected authentication.
- **Projection** — optional event data disclosed in an ID Token or UserInfo.
