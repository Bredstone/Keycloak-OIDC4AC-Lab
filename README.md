# Keycloak + OpenID Connect for Authentication Context (OIDC4AC) Lab

This repository is a local environment for learning about and validating an
experimental Keycloak implementation of
[OIDC4AC](https://bredstone.github.io/oidc4ac/). It brings together a modified
Keycloak distribution, a visual test client, an example email authentication
provider, and automated tests.

The goal is to let anyone try the end-to-end flow without prior knowledge of
the protocol or of Keycloak internals.

## What is OIDC4AC?

[OpenID Connect](https://openid.net/specs/openid-connect-core-1_0.html) lets an
application (the *Relying Party*, or RP) delegate sign-in to an identity
provider (the *OpenID Provider*, or OP). OIDC4AC adds the ability to:

- request authentication requirements, such as password **and** OTP, or
  password **or** a passkey;
- receive a detailed description of the methods that were actually used; and
- control which optional details about those methods appear in the ID Token and
  UserInfo endpoint.

This information is carried by the `amr_details` claim. The complete protocol
— its vocabulary, JSON format, and privacy rules — is available in the
[OIDC4AC documentation](https://bredstone.github.io/oidc4ac/). This project
shows how to apply it to Keycloak; it does not replace the specification.

## What the lab includes

- The [OIDC4AC Keycloak implementation](https://github.com/Bredstone/keycloak-OIDC4AC/tree/oidc4ac-implementation), built locally with the experimental `oidc4ac:v1` feature enabled.
- A disposable realm with the `pwd`, `otp`, `pop` (passkey/WebAuthn), and
  `email` methods.
- A [test client](docs/test-client.md), which is both an RP and a workbench for
  composing, sending, and inspecting OIDC4AC requests.
- An email SPI under `providers/oidc4ac-test-email`, demonstrating that
  custom authentication methods can participate in OIDC4AC.
- HTTP and browser tests that verify the main flows.

## Get started

Prerequisites: Docker Engine with Docker Compose v2, Git, `curl`, and internet
access to download the fork and build dependencies. Java, Maven, and Python are
not required on the host machine.

From the project root, run:

```bash
./dev.sh run
```

The first run downloads and builds the modified Keycloak and example SPI, so it
may take some time. By default, the command stops all running Docker
containers before it starts the lab. If that is not appropriate, use:

```bash
./dev.sh run --no-kill
```

When the services are ready, open:

- Test client: <http://client.localhost:5000>
- Keycloak: <http://keycloak.localhost:8080>
- Disposable email inbox: <http://localhost:5080>

Use `alice` / `Alice-password-123` for the test flows and `admin` / `admin`
for the Keycloak Admin Console. These credentials are only for the local lab.

For a first run, open the test client, keep the password preset, and authorize.
Then try `pwd + otp` and an email preset; the client displays the OTP code and
smtp4dev receives the email code. See [Using the test client](docs/test-client.md)
for the walkthrough.

<!-- Screenshot placeholder: add docs/images/test-client-workbench.png. -->
![OIDC4AC test client workbench](docs/images/test-client-workbench.png)

## How the integration works

Keycloak continues to use its ordinary authenticators and flows. When an OIDC
request contains `amr_details`, the implementation evaluates its requirements
and selects only factors already configured by the administrator. After sign-in,
it records the methods that actually succeeded and safely projects them into
the ID Token and/or UserInfo. An ordinary OIDC request continues to behave as
before.

See [OIDC4AC integration in Keycloak](docs/keycloak-oidc4ac.md) for behavior,
realm configuration, and feature boundaries. For factor-planner details, see
[Browser factor planning](docs/browser-factor-planning.md).

## Extend Keycloak with your own SPI

An application can add an authentication method to Keycloak and make it
available to OIDC4AC. The SPI declares the safe capabilities and details that
the method can provide; the authenticator remains responsible for verifying the
credential. This repository's email SPI is a working reference: it registers
the `email` method, delivers a code, and exposes only the safe
`email_verification_method: code` property.

Read [Creating a custom authentication method with the SPI](docs/custom-authentication-spi.md)
before adapting the example.

## Documentation

The [documentation index](docs/README.md) organizes the guides by goal. The
main entry points are:

- [OIDC4AC integration in Keycloak](docs/keycloak-oidc4ac.md)
- [Using the test client](docs/test-client.md)
- [Usage flows and request examples](docs/usage-flows.md)
- [Configuration reference](docs/configuration-reference.md)
- [Protocol alignment](docs/protocol-alignment.md)

## Useful commands

```bash
./dev.sh run           # start the lab
./dev.sh verify        # start it and check availability/Discovery
./dev.sh test-http     # run HTTP scenarios
./dev.sh test-browser  # run scenarios with virtual WebAuthn
./dev.sh down          # stop services
./dev.sh clean         # also remove generated .runtime/ and .build/ artifacts
```

Use `./dev.sh help` for the complete list. This is an experimental lab, not a
production configuration or conformance certification.
