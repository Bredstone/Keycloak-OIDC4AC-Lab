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
# Edit demo.env and set the private OIDC4AC_DEMO_FLASK_SECRET value.
./scripts/prepare-demo-realm.sh
docker compose --env-file deploy/demo/demo.env \
  -f deploy/demo/docker-compose.yml up -d --build
```

The realm preparation command must complete before `docker compose up`; it
creates the file mounted into the Keycloak container.

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

The example already protects `oidc4ac-mail.duckdns.org` with basic
authentication using the public disposable inbox credentials in the README.
If you rotate that password, generate a new bcrypt hash with
`caddy hash-password --plaintext 'a-disposable-password'` and replace the hash
in the Caddyfile. This protects the disposable inbox from unauthenticated
Internet access.

Validate and start Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
```

Caddy obtains the certificates automatically when DNS resolves correctly and
ports 80/443 are reachable. The certificate is free and is renewed by Caddy.
The smtp4dev service contains only disposable messages and is not intended to
be an open relay or public inbox.

## Smoke checks

```bash
curl --fail --silent --show-error \
  https://oidc4ac-keycloak.duckdns.org/realms/oidc4ac/.well-known/openid-configuration
curl --fail --silent --show-error \
  https://oidc4ac-client.duckdns.org/healthz
docker compose --env-file deploy/demo/demo.env \
  -f deploy/demo/docker-compose.yml ps
```

Use the disposable admin and Alice credentials from the artifact README. Rotate
the hosted admin password and remove the VM after the review period.
