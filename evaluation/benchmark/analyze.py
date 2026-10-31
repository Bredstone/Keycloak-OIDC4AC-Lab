"""Summarizes the timing benchmark runs.

Usage: python3 analyze.py <results-dir>

For each kind of cycle (sso, refresh, login) and condition, it reports the
median and 95th percentile of all measured cycles. For each step of the
configuration chain, it reports the mean paired difference between consecutive
configurations in the same round, with a 95% confidence interval from a
two-level bootstrap that resamples runs and then rounds within each resampled
run (Kalibera and Jones, ISMM 2013). As a steady-state check, it also reports
each difference separately for the first and second halves of the measured
rounds.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

CHAIN = (
    "keycloak_official",
    "fork_feature_disabled",
    "fork_realm_disabled",
    "oidc4ac_without_request",
    "oidc4ac_with_request",
    "oidc4ac_with_full_request",
)
KINDS = ("sso", "refresh", "login")
METRICS = ("client_ms", "server_ms")
BOOTSTRAP = 10_000


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def round_means(samples: list[dict], metric: str) -> dict[int, float]:
    by_round: dict[int, list[float]] = {}
    for sample in samples:
        by_round.setdefault(sample["round"], []).append(sample[metric])
    return {round_index: statistics.mean(values) for round_index, values in by_round.items()}


def bootstrap_interval(differences: list[list[float]], rng: random.Random) -> tuple[float, float]:
    means = []
    for _ in range(BOOTSTRAP):
        runs = rng.choices(differences, k=len(differences))
        resampled = [value for run in runs for value in rng.choices(run, k=len(run))]
        means.append(statistics.fmean(resampled))
    return percentile(means, 0.025), percentile(means, 0.975)


def half_means(differences: list[list[float]]) -> list[float]:
    first = [value for run in differences for value in run[:len(run) // 2]]
    second = [value for run in differences for value in run[len(run) // 2:]]
    return [round(statistics.fmean(first), 3), round(statistics.fmean(second), 3)]


def summarize_kind(runs: list[dict], kind: str, rng: random.Random) -> dict:
    chain = [name for name in CHAIN if name in runs[0]["samples"][kind]]
    summary: dict = {"conditions": {}, "steps": []}
    for name in chain:
        entry = {"cycles": sum(len(run["samples"][kind][name]) for run in runs)}
        for metric in METRICS:
            values = [sample[metric] for run in runs for sample in run["samples"][kind][name]]
            entry[metric] = {"median": round(statistics.median(values), 3),
                             "p95": round(percentile(values, 0.95), 3)}
        summary["conditions"][name] = entry

    for before, after in zip(chain, chain[1:]):
        step = {"from": before, "to": after}
        for metric in METRICS:
            differences = []
            for run in runs:
                first = round_means(run["samples"][kind][before], metric)
                second = round_means(run["samples"][kind][after], metric)
                differences.append([second[index] - first[index] for index in sorted(first)])
            low, high = bootstrap_interval(differences, rng)
            step[metric] = {
                "mean_difference": round(statistics.fmean([d for run in differences for d in run]), 3),
                "ci95": [round(low, 3), round(high, 3)],
                "per_run": [round(statistics.fmean(run), 3) for run in differences],
                "first_and_second_half": half_means(differences),
            }
        summary["steps"].append(step)
    return summary


def main() -> int:
    directory = Path(sys.argv[1])
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("run-*.json"))]
    rng = random.Random(0)
    summary: dict = {"runs": len(runs), "rounds_per_run": [run["measured_rounds"] for run in runs],
                     "sizes": runs[0]["sizes"]}
    for kind in KINDS:
        summary[kind] = summarize_kind(runs, kind, rng)

    # Token payloads carry identifiers and timestamps, so their size may vary
    # slightly between runs; the remaining sizes must be identical.
    variable = ("id_token_payload_bytes", "userinfo_response_bytes")
    for name, sizes in summary["sizes"].items():
        for key in sizes:
            values = [run["sizes"][name][key] for run in runs]
            if key in variable:
                sizes[key] = [min(values), max(values)]
            elif len(set(values)) != 1:
                raise AssertionError(f"{name}: {key} differs between runs.")

    output = json.dumps(summary, indent=2)
    (directory / "summary.json").write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
