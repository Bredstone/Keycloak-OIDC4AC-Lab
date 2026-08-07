Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
# SBSeg 2026 Artifact Appendix

This appendix complements the repository README for the artifact evaluation
process. It is written for reviewers and contains no private credentials or
external infrastructure requirements.

## Submission identity

- **Paper title:** OIDC4AC: Extending OpenID Connect for Structured and Negotiable Authentication Contexts
- **Artifact title:** OIDC4AC on Keycloak: Reproducible Research Artifact
- **Primary repository:** https://github.com/Bredstone/Keycloak-OIDC4AC-Lab/tree/sbseg2026-artifact
- **Companion implementation repository:** https://github.com/Bredstone/keycloak-OIDC4AC/tree/oidc4ac-implementation
- **Reviewed Keycloak commit:** https://github.com/Bredstone/keycloak-OIDC4AC/commit/ec3fd9d3cedc7ad4b347256a0ab30116cb3b8fcc
- **Reviewed Keycloak commit:** `ec3fd9d` from `oidc4ac-implementation`

Submit the primary branch URL above. The companion Keycloak URL is provenance
for the pinned submodule and does not need to be submitted as a second artifact
link.

## Requested seals

The authors request all four seals:

- **SeloD — Available:** the laboratory and the pinned Keycloak implementation
  are available from one stable repository.
- **SeloF — Functional:** reviewers can build the server, start the lab, perform
  a minimal authorization, and run automated HTTP/browser checks.
- **SeloS — Sustainable:** the source is modular, the custom SPI boundary is
  documented, and the principal code paths are organized by component.
- **SeloR — Reproducible Experiments:** the claim-oriented commands in the
  repository README automate the principal protocol and integration checks.

## Reviewer access and restrictions

No cloud account, SSH key, private dataset, paid service, or external
credential is required. All services run locally in Docker. The default users,
client secrets, OTP fixture, and email inbox are disposable and must not be
used outside the evaluation environment.

The first build requires internet access for Docker images and Maven
dependencies. Once those dependencies are cached, the HTTP and browser
experiments can be repeated offline if the required images are available.

## Clean-environment procedure

Reviewers should use a fresh Linux/macOS/Windows host or disposable virtual
machine with Docker Engine, Docker Compose v2, Git, and at least 4 CPU cores,
8 GB RAM, and 15 GB free disk.

```bash
git clone --branch sbseg2026-artifact https://github.com/Bredstone/Keycloak-OIDC4AC-Lab.git
cd Keycloak-OIDC4AC-Lab
git submodule update --init --recursive
./dev.sh verify
```

If the initial smoke check succeeds, the claim commands in the root README can
be run independently. Generated state is confined to ignored `.runtime/`,
`.build/`, and `target/` directories. The build stages the pinned Keycloak
submodule into `.runtime/keycloak-source`; it never builds in the tracked
submodule worktree. Default Docker base images are pinned by manifest digest.

## Claim-to-evidence map

| Claim | Primary evidence | Expected observation |
| --- | --- | --- |
| OIDC4AC request and disclosure semantics | `./dev.sh test-http` | Discovery, requirements, constraints, projections, snapshots, and generic failures pass |
| Browser factor planning and passkeys | `./dev.sh test-browser` | Configured factor plans, `pop`, alternatives, and cancellation are exercised |
| Custom SPI extensibility | `./dev.sh provider-build` followed by `./dev.sh test-http` | The email provider is built, advertised, invoked, and represented without secrets |
| Feature isolation | `./dev.sh test-disabled` | OIDC4AC is unavailable while ordinary OIDC remains available |
| Code and environment checks | `./dev.sh lint` | Compose, Python, shell, realm, and provider checks pass |

## Expected limitations

The artifact does not claim validation of every Keycloak storage backend,
multi-node/offline-token failover deployment, hardware-specific WebAuthn
attestation, or every encrypted-JARM algorithm combination. These boundaries
are described in [Protocol alignment](../docs/protocol-alignment.md) and do not
require additional reviewer resources.
