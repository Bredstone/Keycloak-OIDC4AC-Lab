# Public hosted instance

The project has an optional public instance for quickly trying the OIDC4AC
implementation. It is a convenience for interactive exploration; the local
Docker workflow remains the reproducible reference for the artifact.

## Access points

| Service | URL | Purpose |
| --- | --- | --- |
| Test client | <https://oidc4ac-client.duckdns.org> | Compose OIDC4AC requests |
| Keycloak | <https://oidc4ac-keycloak.duckdns.org> | OIDC provider and Account Console |
| Keycloak Admin Console | <https://oidc4ac-keycloak.duckdns.org/admin/oidc4ac/console/> | Inspect the hosted `oidc4ac` realm |
| Email inbox | <https://oidc4ac-mail.duckdns.org> | Inspect disposable verification messages |

The hosted instance uses these disposable credentials:

| Account | Username | Password |
| --- | --- | --- |
| Realm administration (read-only) | `oidc4ac-demo-admin` | `O4AC-3500b25109a07bf339344f1c03f2e83b` |
| Test user | `alice` | `Alice-password-123` |

The administration account can inspect the `oidc4ac` realm and its
authentication flows. It cannot modify users, clients, or flows. The email
inbox requires no login and contains only disposable test messages.

## Sign in to the Admin Console

To inspect the configured realm and authentication flows:

1. Open the [Keycloak Admin Console](https://oidc4ac-keycloak.duckdns.org/admin/oidc4ac/console/).
2. Sign in with the **Realm administration (read-only)** credentials above.
3. Confirm that the realm selector shows `oidc4ac`.
4. Open **Authentication → Flows** to inspect the OIDC4AC browser flow.

The direct URL selects the `oidc4ac` realm. This account is not the private
master-realm bootstrap administrator and cannot manage the Keycloak server or
other realms.

## Try a request

1. Open the test client and choose a preset, such as **Essential password**.
2. Click **Start authorization** and sign in as Alice.
3. Inspect the verified authentication context on the result page.
4. Open **Factor tools** to access the OTP helper, email inbox, and WebAuthn
   setup in one place.

To use WebAuthn, open the **Account Console** from **Factor tools**, sign in as
Alice, and register a passkey under **Security** or **Signing in**. Return to
the test client and choose a preset containing `pop`. Each browser or device
can register its own credential. The hosted instance uses one shared test
account, so registered passkeys remain valid for that account.

## Scope of the hosted instance

The instance is disposable and intended for protocol exploration. Do not use
the credentials, email inbox, OTP seed, or WebAuthn account for real data. The
hosted process is a single instance and is not a demonstration of production
hardening, high availability, or multi-node session storage.

For a clean, reproducible run, follow the [local installation instructions](../README.md)
and the [test-client guide](test-client.md).
