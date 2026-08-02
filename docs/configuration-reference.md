# Configuration reference

This page describes the disposable environment created by the lab. The
canonical values are in `docker-compose.yml`, `config/realm-import.json`, and
the scripts under `scripts/`.

## Runtime services

| Service | Default host port | Role |
| --- | ---: | --- |
| Keycloak | 8080 | OIDC provider and Admin Console |
| Flask test client | 5000 | Request builder and relying party |
| smtp4dev SMTP | 2525 | Email provider delivery sink |
| smtp4dev web UI | 5080 | Read disposable verification messages |
| Browser-profile Keycloak | 8186 | Isolated browser/WebAuthn run |
| Browser-profile client | 5003 | Isolated browser test client |
| Feature-disabled Keycloak | 8187 | Discovery/runtime gate regression |

The issuer uses `keycloak.localhost` and the client uses `client.localhost` so
browser redirects and token validation use stable hostnames. Modern browsers
resolve `*.localhost` to loopback.

## Source and build variables

The default source helper fetches:

```text
Repository: https://github.com/Bredstone/keycloak-OIDC4AC.git
Ref:        oidc4ac-implementation
Checkout:   .runtime/keycloak-source
```

For local development, set one of these before `./dev.sh build`:

| Variable | Meaning |
| --- | --- |
| `OIDC4AC_LAB_KEYCLOAK_REPO` | Existing local Keycloak checkout; avoids cloning |
| `OIDC4AC_LAB_KEYCLOAK_REPO_URL` | Remote repository to clone/fetch |
| `OIDC4AC_LAB_KEYCLOAK_REF` | Branch, tag, or ref to build |
| `OIDC4AC_LAB_BUILDER_IMAGE` | Maven builder image override |

The helper refreshes a managed generated checkout and may reset that generated
directory to the selected ref. Do not point it at an uncommitted checkout
unless you understand that behavior; use `OIDC4AC_LAB_KEYCLOAK_REPO` with a
working copy only when you are intentionally testing that source.

## Ports and process variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `OIDC4AC_LAB_HTTP_PORT` | `8080` | Host port for the regular Keycloak process |
| `OIDC4AC_LAB_CLIENT_PORT` | `5000` | Host port for the regular client |
| `OIDC4AC_LAB_ISSUER` | derived from the Keycloak port | Issuer used by Compose/client |
| `OIDC4AC_LAB_ADMIN_USERNAME` | `admin` | Bootstrap administrator name |
| `OIDC4AC_LAB_ADMIN_PASSWORD` | `admin` | Imported administrator password |

Use `./dev.sh run --no-kill` to preserve unrelated containers and a running
Keycloak process. It is a command-line option, not an environment variable.

If a port is occupied, use `./dev.sh status`, stop the old lab with
`./dev.sh down`, or choose a different regular-run port. The browser and
disabled profiles have their own fixed ports.

## Imported realm

`config/realm-import.json` imports realm `oidc4ac` with:

- OIDC4AC enabled for the realm;
- the `oidc4ac lab browser` browser flow;
- the OIDC4AC factor planner and `oidc4ac-factors` container;
- configured `pwd`, `otp`, `pop`, and `email` factor subflows;
- clients `oidc4ac-test-client` and `oidc4ac-consent-test-client`;
- Alice's password and disposable OTP fixture; and
- localhost smtp4dev settings for the email provider.

The realm import is a test fixture, not a recommended production baseline.
Realm and client disclosure policies should be reviewed before exposing
optional authentication metadata or properties to a real RP.

## Building the optional provider

The email authenticator is a Maven project with its own `pom.xml`. Keycloak
APIs are `provided`; the provider JAR does not bundle Keycloak classes. Build
it with:

```bash
./dev.sh provider-build
```

The output JAR is generated under
`providers/oidc4ac-test-email/target/` and is ignored by Git. The regular
launcher copies it into the temporary Keycloak distribution before startup; the
Docker image used by the browser profile copies it into
`/opt/keycloak/providers`.

## Manual lifecycle

The wrapper is recommended, but the individual steps are useful when
debugging:

```bash
./dev.sh build
./dev.sh provider-build
docker compose up -d smtp4dev
bash scripts/start-keycloak.sh
docker compose up --build
```

For tests, use `./dev.sh test-http`, `./dev.sh test-browser`, or
`./dev.sh test`. Do not run the regular and browser profiles against the same
ports.

## Cleanup and data safety

```bash
./dev.sh down    # stop this lab's services
./dev.sh clean   # stop and remove generated runtime/build state
```

`clean` removes only generated `.runtime/` and `.build/` state. The Docker
volumes and imported realm are disposable; never use the default credentials
or OTP seed outside this lab.
