# Testing and reproducibility

Run these commands from the repository root after installation. Each suite can
be run independently after the required build step. The main build skips
upstream Keycloak unit tests; the commands below run the lab's integration and
quality checks.

## OIDC4AC requests and disclosure

**Command:**

```bash
./dev.sh test-http
```

**Expected resources:** 4 CPU cores, 8 GB RAM, 15 GB free disk; approximately
5–15 minutes after images and Maven dependencies are cached.

**Expected result:** the HTTP suite completes its authorization-code scenarios
covering Discovery, password/OTP requirements, recursive `all_of`/`one_of`,
constraints, ID Token/UserInfo projections, snapshots, refresh, disclosure
policy, and generic requirement failures.

See [Usage flows](usage-flows.md) and
[Protocol alignment](protocol-alignment.md) for the expected protocol
behavior.

## Browser factor planning and passkeys

**Command:**

```bash
./dev.sh test-browser
```

**Expected resources:** 4 CPU cores, 8 GB RAM, 15 GB free disk; approximately
5–15 minutes after the regular Keycloak build is cached.

**Expected result:** the isolated browser profile starts Keycloak on port 8186
and the test client on port 5003, then exercises configured factor planning,
OTP, passkey/WebAuthn `pop` mapping, alternative-branch behavior, and explicit
user cancellation.

See [Browser factor planning](browser-factor-planning.md).

## Custom authentication methods

**Commands:**

```bash
./dev.sh provider-build
./dev.sh test-http
```

**Expected resources:** the same environment as the HTTP suite; provider compilation
normally takes under 5 minutes after Maven dependencies are cached.

**Expected result:** the `oidc4ac-test-email` JAR is compiled against the
pinned Keycloak SPI, loaded into the server, advertised through Discovery, and
used by the email factor. The resulting `amr_details` contains only the
safe `email_verification_method: code` property.

See [Creating a custom authentication method with the SPI](custom-authentication-spi.md).

## Feature isolation and ordinary OIDC behavior

**Command:**

```bash
./dev.sh test-disabled
```

**Expected resources:** 4 CPU cores, 8 GB RAM, 10 GB free disk; approximately
5–10 minutes on a cold Docker/Maven cache.

**Expected result:** the feature-disabled profile does not advertise or process
OIDC4AC requests while the ordinary Keycloak/OIDC paths remain available.

## Code quality and environment status

**Commands:**

```bash
./dev.sh lint
./dev.sh status
```

**Expected resources:** 2 CPU cores, 4 GB RAM, and 5 GB free disk; normally
under 5 minutes after dependencies are cached. Host lint dependencies must be
installed with `python3 -m pip install -r requirements-dev.txt`.

**Expected result:** Compose, Python, shell, realm JSON, provider XML, and
provider formatting checks pass, and `status` reports the selected staged
Keycloak source and local services.

## Repeating a run

The first build downloads Docker images and Maven dependencies. After these
are cached, tests can run offline if all required images and dependencies are
available. Build output stays in ignored `.build/`, `.runtime/`, and `target/`
directories; the tracked Keycloak submodule is not used as a build worktree.
Run `./dev.sh down` to stop the lab.

For resources, dependencies, and a first smoke check, see the
[installation instructions](../README.md). For coverage boundaries, see
[Protocol alignment](protocol-alignment.md).
