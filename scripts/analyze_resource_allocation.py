#!/usr/bin/env python3
"""Offline finite-horizon cartoons; no model, network, service or task execution.

All economic inputs are explicit scenarios. Historical timings are descriptive.
This is a calculation artifact, not a scheduler or automatic admission policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from functools import cache
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capacity(scenario: dict, recipe: dict) -> dict:
    """Fluid capacity with separate budgets, unlimited eligible attempts, demand cap.

    This is a relaxed planning bound, not a finite-queue success probability.
    Per-attempt costs include failed attempts; no retry-until-success claim.
    """
    p = recipe["acceptance_probability"]
    bounds = {"demand": scenario["accepted_demand"]}
    for resource, cost in (
        ("gpu", "gpu_lease_seconds_per_attempt"),
        ("outer", "outer_active_seconds_per_attempt"),
        ("human", "human_attention_seconds_per_attempt"),
    ):
        bounds[resource] = p * scenario[f"{resource}_hours"] * 3600 / recipe[cost]
    total = min(bounds.values())
    return {
        "expected_accepted_capacity": total,
        "binding_constraints": [k for k, v in bounds.items() if abs(v - total) < 1e-9],
        "bounds": bounds,
    }


def voi(config: dict, exposure: float) -> dict:
    """Exact finite enumeration and sequential stopping for a two-state toy.

    Opportunity costs have already been converted to one chosen unit. Exposure
    is a fixed workload that remains deliverable; calendar truncation would need
    a different model. Probe results don't themselves change the candidate.
    """
    prior = config["prior_good"]
    good = exposure * config["good_fraction_time_saved"]
    bad = exposure * config["bad_fraction_time_saved"]
    adoption_cost = config["adoption_cost_gpu_hour_equivalents"]
    setup = config["probe_setup_cost_gpu_hour_equivalents"]
    cost = config["per_observation_cost_gpu_hour_equivalents"]
    sg = config["positive_signal_probability_if_good"]
    sb = config["positive_signal_probability_if_bad"]
    limit = config["maximum_observations"]

    def adoption_value(belief: float) -> float:
        return belief * good + (1 - belief) * bad - adoption_cost

    def posterior(n: int, k: int) -> float:
        a = prior * sg**k * (1 - sg) ** (n - k)
        b = (1 - prior) * sb**k * (1 - sb) ** (n - k)
        return a / (a + b)

    current = max(0.0, adoption_value(prior))
    evpi = (
        prior * max(0.0, good - adoption_cost)
        + (1 - prior) * max(0.0, bad - adoption_cost)
        - current
    )
    fixed = []
    for n in range(limit + 1):
        informed = 0.0
        for k in range(n + 1):
            mass = math.comb(n, k) * (
                prior * sg**k * (1 - sg) ** (n - k)
                + (1 - prior) * sb**k * (1 - sb) ** (n - k)
            )
            informed += mass * max(0.0, adoption_value(posterior(n, k)))
        gross = informed - current
        expense = setup + n * cost if n else 0.0
        fixed.append({"n": n, "gross_evsi": gross, "net_gain": gross - expense})
        # A noisy signal cannot exceed perfect information; tiny error is roundoff.
        assert -1e-10 <= gross <= evpi + 1e-10

    @cache
    def policy(n: int, k: int) -> tuple[float, float, str]:
        belief = posterior(n, k)
        stop = max(0.0, adoption_value(belief))
        stop_action = "adopt" if adoption_value(belief) > 0 else "retain"
        if n == limit:
            return stop, 0.0, stop_action
        prob_positive = belief * sg + (1 - belief) * sb
        positive, np, _ = policy(n + 1, k + 1)
        negative, nn, _ = policy(n + 1, k)
        continuation = -cost + prob_positive * positive + (1 - prob_positive) * negative
        if continuation <= stop + 1e-12:
            return stop, 0.0, stop_action
        return continuation, 1 + prob_positive * np + (1 - prob_positive) * nn, "sample"

    value, observations, action = policy(0, 0)
    worthwhile = action == "sample" and value - setup > current
    adaptive_gain = value - setup - current if worthwhile else 0.0
    assert adaptive_gain >= max(r["net_gain"] for r in fixed) - 1e-9
    assert adaptive_gain <= evpi + 1e-9
    return {
        "future_baseline_gpu_hours": exposure,
        "current_adopt_gain": adoption_value(prior),
        "free_perfect_information_value": evpi,
        "fixed_samples": fixed,
        "best_fixed": max(fixed, key=lambda r: r["net_gain"]),
        "adaptive_net_gain": adaptive_gain,
        "adaptive_expected_observations": observations if worthwhile else 0,
        "adaptive_first_action": (
            "probe"
            if worthwhile
            else ("adopt" if adoption_value(prior) > 0 else "retain")
        ),
        "adaptive_boundaries": [
            {
                "n": n,
                "positive": k,
                "posterior_good": posterior(n, k),
                "action_after_setup_paid": policy(n, k)[2],
            }
            for n in range(limit + 1)
            for k in range(n + 1)
        ],
    }


def analyze(config: dict, evidence: dict) -> dict:
    capacities = []
    for scenario in config["capacity_scenarios"]:
        for change in config["oracle_changes"]:
            recipe = config["production_baseline"] | change["overrides"]
            capacities.append(
                {
                    "scenario": scenario["name"],
                    "change": change["name"],
                    **capacity(scenario, recipe),
                }
            )

    break_even = []
    b = config["efficiency_break_even"]
    for ratio in b["outer_to_gpu_shadow_price_ratio"]:
        expense = b["investment_gpu_hours"] + ratio * b["investment_outer_hours"]
        for fraction in b["affected_runtime_fraction"]:
            for reduction in b["fraction_time_saved_on_affected_work"]:
                break_even.append(
                    {
                        "outer_to_gpu_shadow_price_ratio": ratio,
                        "affected_runtime_fraction": fraction,
                        "fraction_time_saved_on_affected_work": reduction,
                        "break_even_baseline_gpu_hours": expense
                        / (fraction * reduction),
                        "net_gpu_hour_equivalents_by_exposure": {
                            str(hours): hours * fraction * reduction - expense
                            for hours in b["future_baseline_gpu_hours"]
                        },
                    }
                )

    qwen = next(r for r in evidence["qualification_panel"] if r["model"] == "qwen")
    assert qwen["request_count"] == qwen["response_count"]
    precision = config["precision_toy"]
    normal = NormalDist()
    z = normal.inv_cdf(1 - precision["two_sided_alpha"] / 2)
    z += normal.inv_cdf(precision["power"])
    precision_rows = []
    for sd in precision["paired_difference_sd_fraction"]:
        for delta in precision["target_mean_reduction_fraction"]:
            n = math.ceil((z * sd / delta) ** 2)
            precision_rows.append(
                {
                    "paired_difference_sd_fraction": sd,
                    "target_mean_reduction_fraction": delta,
                    "approximate_pairs": n,
                    "gpu_hours": n
                    * precision["two_arm_mean_gpu_seconds_per_pair"]
                    / 3600,
                }
            )
    reliability = config["reliability_toy"]
    return {
        "status": "Computed cartoons and descriptive bounds; not experimental findings",
        "capacity": capacities,
        "efficiency_break_even": break_even,
        "voi": [
            voi(config["voi_toy"], hours)
            for hours in config["voi_toy"]["future_baseline_gpu_hours"]
        ],
        "precision": precision_rows,
        "reliability": [
            {
                "p": p,
                "n": n,
                "probability_all_pass": p**n,
                "one_sided_95_lower_if_all_pass": 0.05 ** (1 / n),
            }
            for p in reliability["true_success_probabilities"]
            for n in reliability["panel_sizes"]
        ],
        "cache_only_ceiling": {
            "scope": "Nine original Qwen v2 assignments, all recorded responses available",
            "task_fraction": qwen["reported_prefill_task_fraction"],
            "dispatch_fraction": qwen["reported_prefill_dispatch_fraction"],
            "seconds": qwen["reported_prefill_seconds"],
            "qualification": "Hypothetical deletion of ALL measured prefill with fixed trajectories. Not achievable scoped-cache savings, and not a ceiling on behavioral or decode-context improvements.",
        },
    }


def self_check() -> None:
    """Independent limiting cases for formulas that drive the recommendations."""
    scenario = {
        "gpu_hours": 1,
        "outer_hours": 100,
        "human_hours": 100,
        "accepted_demand": 1000,
    }
    recipe = {
        "acceptance_probability": 0.5,
        "gpu_lease_seconds_per_attempt": 60,
        "outer_active_seconds_per_attempt": 1,
        "human_attention_seconds_per_attempt": 1,
    }
    assert capacity(scenario, recipe)["expected_accepted_capacity"] == 30
    assert (
        capacity(scenario, recipe | {"acceptance_probability": 0})[
            "expected_accepted_capacity"
        ]
        == 0
    )
    assert (
        capacity(scenario | {"accepted_demand": 2}, recipe)[
            "expected_accepted_capacity"
        ]
        == 2
    )
    # An uninformative diagnostic cannot improve the decision.
    toy = {
        "prior_good": 0.3,
        "good_fraction_time_saved": 0.1,
        "bad_fraction_time_saved": -0.05,
        "adoption_cost_gpu_hour_equivalents": 1,
        "probe_setup_cost_gpu_hour_equivalents": 0.15,
        "per_observation_cost_gpu_hour_equivalents": 0.08,
        "positive_signal_probability_if_good": 0.5,
        "positive_signal_probability_if_bad": 0.5,
        "maximum_observations": 8,
    }
    result = voi(toy, 40)
    assert result["adaptive_first_action"] == "retain"
    assert all(abs(r["gross_evsi"]) < 1e-10 for r in result["fixed_samples"])
    # With no positive gain even in the good state, information is worthless.
    assert voi(toy, 10)["free_perfect_information_value"] == 0
    assert voi(toy | {"prior_good": 0.9}, 40)["adaptive_first_action"] == "adopt"
    informative = voi(
        toy
        | {
            "positive_signal_probability_if_good": 0.75,
            "positive_signal_probability_if_bad": 0.25,
        },
        40,
    )
    # One positive signal has probability .4, posterior .5625 and adoption
    # gain .375; the negative signal leaves the candidate unadopted.
    assert math.isclose(informative["fixed_samples"][1]["gross_evsi"], 0.4 * 0.375)
    assert math.isclose(informative["fixed_samples"][2]["gross_evsi"], 0.375)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs/resource-allocation-scenarios-v1.json",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "results/resource-allocation-evidence-001.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    self_check()
    result = analyze(
        json.loads(args.config.read_text()), json.loads(args.evidence.read_text())
    )
    result["input_sha256"] = {
        "config": digest(args.config),
        "evidence": digest(args.evidence),
        "script": digest(Path(__file__)),
    }
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized)
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
