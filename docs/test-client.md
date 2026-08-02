# Using the test client

The test client is a small Flask application that acts as both an RP and an
experiment workbench. It does not simulate responses: it sends a real OIDC
authorization to Keycloak, validates the response, and displays the received
data.

## Start the environment

From the repository root, run:

```bash
./dev.sh run
```

Open <http://client.localhost:5000>. Use `alice` / `Alice-password-123` when
Keycloak asks for credentials. To stop the lab, press `Ctrl-C` in the terminal
running the command or run `./dev.sh down` from another terminal.

## Run your first request

1. On the home page, keep the **Essential password** preset.
2. Keep **ID Token** selected and click **Start authorization**.
3. Sign in as Alice in Keycloak.
4. On the result page, compare the sent request, the OP Discovery document,
   and the `amr_details` claim in the ID Token.

The result should show the `pwd` method and when it was executed. This is the
simplest way to see that OIDC4AC describes the authentication that occurred,
rather than only token issuance.

<!-- Screenshot placeholder: add docs/images/test-client-result.png. -->
![Test client authorization result with authentication context](images/test-client-result.png)

## Discovery, builder, and JSON editor

Before it renders the interface, the client reads the issuer's OIDC Discovery
document. The identifiers, properties, and finite options suggested by the
builder therefore come from the running Keycloak instance — including methods
provided by a custom SPI.

The JSON editor is the source of truth: its contents are sent, without
conversion to a private format, as the OIDC `claims` parameter. The preview
button only helps inspect the JSON before authorization. Use the visual builder
to get started and the editor to test a specific request.

The presets cover password, OTP, passkey, email, nested expressions, and error
cases. For their expected behavior, copyable JSON, and an explanation of
`essential`, `all_of`, `one_of`, properties, and errors, see
[Usage flows](usage-flows.md).

## What the result page shows

The page shows the sent request, the Discovery document used by the builder,
the validated ID Token, and UserInfo when requested. It also exposes a
diagnostic view of the access token to confirm that `amr_details` is not copied
into it in this lab.

The client keeps data only for its local session and is designed for testing.
Do not use it directly as the basis for a production RP.
