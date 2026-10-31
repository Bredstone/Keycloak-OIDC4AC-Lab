# OIDC4AC evaluation

This directory holds the scripts and raw results behind the functional,
compatibility, and quantitative evaluation of OIDC4AC reported in the
dissertation *Extending OpenID Connect for Context-Aware Authentication*
(Section 7). It is an audit artifact, not a claim of production performance.

All recorded results used the implementation at commit
[`5bd7641`](https://github.com/Bredstone/keycloak-OIDC4AC/commit/5bd7641d6813828d125932d6c2a2d1d6f91862a7),
the one pinned by this laboratory. Every script runs from the repository root
and uses its own Docker Compose project, so it does not stop a laboratory
started with `./dev.sh`.

## Functional results

`functional-results.md` records the unit tests (59), the laboratory's HTTP
scenarios (37), regression scenario (1), and browser scenarios (9), all
passing. The laboratory's suites are described in [Testing and
reproducibility](../docs/testing.md).

## Compatibility matrix

`compatibility/oidc4ac-compatibility-matrix.py` combines RPs and IdPs that do
or do not implement OIDC4AC: an ordinary RP against IdPs with OIDC4AC disabled
and enabled, an OIDC4AC RP that falls back after Discovery against an IdP with
OIDC4AC disabled, an OIDC4AC RP against an IdP with OIDC4AC enabled, and an
OIDC4AC RP sending an essential `pop` request to an IdP that offers only
informational support. It runs inside the laboratory's HTTP test image against
two instances: OIDC4AC enabled (Keycloak on port 8186, test client on 5003) and
OIDC4AC disabled (Keycloak on port 8187, test client on
`client.localhost:5001`).

```sh
evaluation/compatibility/run-compatibility-matrix.sh
```

The recorded output is `compatibility/compatibility-matrix-result.txt`. The
matrix exercises configurations of the laboratory's reference RP rather than an
independently developed RP, so it is evidence of implementation-level
compatibility only.

## Message sizes

```sh
evaluation/benchmark/run-message-sizes.sh [output-dir]
```

The script starts the laboratory's browser profile and runs
`benchmark/message-sizes.py` in its Playwright image. It sends the
authentication request itself, captures the code, exchanges it at the token
endpoint, and calls UserInfo, so it measures the encoded ID Token, its decoded
payload, and the UserInfo body as Keycloak sends them. It covers three cases:
no `amr_details` request, `pwd` with every metadata member and property that
Discovery advertises, and every advertised method (`pwd`, `otp`, `pop`,
`email`) with the same detail, completed in one authentication. The recorded
result is `benchmark/results/message-sizes.json`.

## Processing time

```sh
evaluation/benchmark/run-benchmark.sh [output-dir]
python3 evaluation/benchmark/analyze.py <output-dir>
```

Results go to `.runtime/evaluation/timing` by default. The script downloads the
official Keycloak 26.7.0 distribution into `.build/` and verifies its SHA-1
(`d0525120aa3073486bc54a66760cab0cbeedf0dd`) before building it on the same
base image and JVM as the fork. `OIDC4AC_BENCHMARK_RUNS`,
`OIDC4AC_BENCHMARK_WARMUPS`, and `OIDC4AC_BENCHMARK_SAMPLES` shorten a trial
run.

Six configurations form a chain, each adding one element to the previous one:
the official distribution, the fork with the feature disabled, the feature
enabled with the realm disabled, the realm enabled without a request, a `pwd`
request, and the all-methods request. The first three run on separate Keycloak
instances; the last four share the instance with the feature enabled, which
hosts a realm with OIDC4AC disabled and another with it enabled. Each round
measures three scenarios in random order: (i) interactive authentication of a
password-only user, (ii) an authentication request within an established SSO
session, and (iii) a token refresh. The all-methods condition has no scenario
(i); its SSO session is established once per run in the browser by
`benchmark/seed-session.py`, so no factor is collected during measurement. For
each scenario, `benchmark/timing-benchmark.py` records the total time and the
time Keycloak spent processing its requests, read from Keycloak's HTTP metrics
before and after the scenario.

Each Keycloak instance runs pinned to both threads of one performance core,
with a 2 GB memory limit; the cores and the start order rotate between runs,
and every instance serves the same number of scenarios per round. Each run
starts fresh containers, discards 50 warm-up rounds, and measures 100.
`benchmark/analyze.py` reports medians, 95th percentiles, and, for each step
of the chain, the mean paired difference within rounds with a 95% confidence
interval from a two-level bootstrap (runs, then rounds within runs), plus
first- and second-half means as a steady-state check.

The recorded runs were executed on 2026-10-30 on a Samsung Galaxy Book3 Ultra
(Intel Core i9-13900H, 32 GB LPDDR5) with Ubuntu 26.04.1 LTS (Linux 7.0),
Docker 28.2, Temurin 21.0.11, and the performance power profile
(`intel_pstate`, EPP `performance`). The raw runs and their summary are in
`benchmark/results/timing/`.
