# Hosted reviewer demonstration

This optional deployment publishes a disposable OIDC4AC demonstration on a
small Linux VM. It is separate from the local artifact Compose file so the
reproducible test commands remain unchanged.

## Prerequisites

- a VM with Docker Engine and Docker Compose v2;
- the reviewed `sbseg2026-artifact` checkout, including its Keycloak submodule;
- the generated `.build/keycloak-26.7.0.tar.gz` and provider JAR;
- three DNS names pointing to the VM; the example uses DuckDNS;
- TCP ports 80 and 443 allowed to the VM.

The demo uses these names by default:

| Service | Public URL |
| --- | --- |
| Keycloak | `https://oidc4ac-keycloak.duckdns.org` |
| Test client | `https://oidc4ac-client.duckdns.org` |
| Disposable inbox | `https://oidc4ac-mail.duckdns.org` |

Replace them in `deploy/demo/demo.env` and `deploy/demo/Caddyfile.example` if your
DuckDNS names differ.

## Prepare and start

```bash
cp deploy/demo/demo.env.example deploy/demo/demo.env
chmod 600 deploy/demo/demo.env
# Edit demo.env: set private bootstrap/Flask secrets and keep the public
# reviewer credentials only for this disposable demo.
./scripts/prepare-demo-realm.sh
docker compose --env-file deploy/demo/demo.env \
  -f deploy/demo/docker-compose.yml up -d --build
```

The realm preparation command must complete before `docker compose up`; it
creates the file mounted into the Keycloak container.

The generated realm contains a separate reviewer account with only the
read-only `view-realm` role. Use it at
`https://oidc4ac-keycloak.duckdns.org/admin/oidc4ac/console` to inspect the
realm and its authentication flows. The bootstrap account configured through
`OIDC4AC_DEMO_BOOTSTRAP_USERNAME` and `OIDC4AC_DEMO_BOOTSTRAP_PASSWORD` belongs
to the master realm and should remain private.

To exercise WebAuthn, use the test user rather than the reviewer administrator:
open `https://oidc4ac-keycloak.duckdns.org/realms/oidc4ac/account`, sign in as
`alice / Alice-password-123`, open **Security** (or **Signing in**), and create
a passkey. Then return to the test client, open **Factor tools**, and run a
request containing the `pop` method. Each reviewer must register a credential
in their own browser profile; credentials are local to that browser/device.

### Updating an existing VM

Realm imports are applied when the realm is first created. If the hosted VM
already has a persistent `keycloak-demo-data` volume, do not delete it merely
to apply these changes. Instead, use the current bootstrap administrator once
to create `oidc4ac-demo-admin` in the `oidc4ac` realm, set the documented
disposable password, and assign only the `realm-management` client role
`view-realm`. Then use the realm-scoped account at the URL above and keep the
bootstrap credentials private. Remove the `basic_auth` block from the mail
site in `/etc/caddy/Caddyfile`, validate it, and reload Caddy:

Update `demo.env` so it contains the new private bootstrap variables and the
public reviewer variables from `deploy/demo/demo.env.example`; the old
`OIDC4AC_DEMO_ADMIN_*` names are no longer used by the hosted Compose file.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Finally pull the updated repository and rebuild only the client:

```bash
git pull --ff-only
docker compose --env-file deploy/demo/demo.env \
  -f deploy/demo/docker-compose.yml up -d --build test-client
```

The Keycloak image is built from the reviewed distribution and example SPI
already prepared by `./dev.sh build` and `./dev.sh provider-build`.

## HTTPS reverse proxy

Install Caddy on Ubuntu, then copy `deploy/demo/Caddyfile.example` to
`/etc/caddy/Caddyfile`:

```bash
sudo apt-get update
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy
sudo cp deploy/demo/Caddyfile.example /etc/caddy/Caddyfile
```

The example intentionally leaves `oidc4ac-mail.duckdns.org` public. This keeps
the reviewer workflow simple: email-based factors can be inspected without a
second login. The inbox contains only disposable lab messages; never route real
mail or personal data to it.

Validate and start Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable caddy
sudo systemctl restart caddy
```

Caddy obtains the certificates automatically when DNS resolves correctly and
ports 80/443 are reachable. The certificate is free and is renewed by Caddy.
The smtp4dev service contains only disposable messages. It is not an open relay;
its web inbox is public by design for this reviewer deployment.

## Smoke checks

The public-URL checks are best run from a different machine or network than
the VM. Some cloud network paths do not support testing a VM's public IP from
that same VM. To test Caddy locally while preserving the hostname and TLS SNI,
use `--resolve`:

```bash
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  --resolve oidc4ac-keycloak.duckdns.org:443:127.0.0.1 \
  https://oidc4ac-keycloak.duckdns.org/realms/oidc4ac/.well-known/openid-configuration
```

From a different machine, use the public URLs:

```bash
curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  https://oidc4ac-keycloak.duckdns.org/realms/oidc4ac/.well-known/openid-configuration
curl --fail --silent --show-error --connect-timeout 10 --max-time 30 \
  https://oidc4ac-client.duckdns.org/healthz
docker compose --env-file deploy/demo/demo.env \
  -f deploy/demo/docker-compose.yml ps
```

Use the realm-scoped reviewer account and Alice credentials from the artifact
README. The bootstrap account used to start Keycloak is not a reviewer account
and should remain private. Remove the VM after the review period.
