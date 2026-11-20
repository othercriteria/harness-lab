"""Replay the two historical short-task comparisons for issue #21 (CPU only)."""

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

RESULTS = Path(__file__).resolve().parents[1] / "results"


def read(name):
    return json.loads((RESULTS / name).read_bytes())


def backtest(campaigns, default):
    training = defaultdict(list)
    setup = defaultdict(list)
    test = defaultdict(dict)
    ceilings = {c["ceiling"] for c in campaigns}
    (ceiling,) = ceilings
    for campaign in campaigns:
        arm = campaign["arm"]
        for trial in campaign["trials"]:
            if trial["stage"] == "train":
                training[arm].append(trial)
                setup[arm].append(campaign["load"] + (campaign["warmup"] or 0))
            else:
                key = trial["seed"], trial["task"]
                if key in test[arm]:
                    raise ValueError(f"duplicate test observation: {arm}, {key}")
                test[arm][key] = trial

    expected = {(t["seed"], t["task"]) for t in training[default]}
    means = {}
    screen = {}
    for arm, trials in training.items():
        keys = [(t["seed"], t["task"]) for t in trials]
        if set(keys) != expected or len(keys) != len(expected):
            raise ValueError(f"incomplete matched development cohort: {arm}")
        means[arm] = mean(t["seconds"] for t in trials)
        # Use only prior observations. Include the whole final generation, even
        # when it contained reasoning. This proxy is not a physical lower bound.
        proxies = []
        for t in trials:
            p = t["probe"]
            prompt = p.get("cold_prefix", p["initial"])
            proxies.append((prompt["prompt_ms"] + p["finish"]["generation_ms"]) / 1000)
        screen[arm] = {
            "full": sum(t["accepted"] for t in trials),
            "n": len(trials),
            "mean_task_s": round(means[arm], 3),
            "max_prefill_plus_finish_s": round(max(proxies), 3),
            "time_proxy_fits": max(proxies) <= ceiling,
            "setup_range_s": [round(f(setup[arm]), 3) for f in (min, max)],
        }

    eligible = [
        arm for arm, v in screen.items() if v["time_proxy_fits"] and v["full"] == v["n"]
    ]
    decisions = []
    for resident in [None, *sorted(training)]:
        baseline = resident or default
        for price in ("free", "low", "high"):

            def charge(arm):
                if arm == resident or price == "free":
                    return 0
                return (min if price == "low" else max)(setup[arm])

            chosen = min(
                eligible,
                key=lambda arm: (means[arm] + charge(arm), arm != baseline, arm),
            )
            row = {
                "resident": resident,
                "scenario": price,
                "baseline": baseline,
                "chosen": chosen,
            }
            if (
                baseline not in test
                or chosen not in test
                or test[chosen].keys() != test[baseline].keys()
            ):
                row["score"] = "missing paired outcomes"
            else:
                rows = []
                for seed, task in sorted(test[baseline]):
                    left, right = (test[a][seed, task] for a in (baseline, chosen))
                    rows.append(
                        {
                            "seed": seed,
                            "task": task,
                            "baseline_full": left["accepted"],
                            "chosen_full": right["accepted"],
                            "baseline_s": left["seconds"] + charge(baseline),
                            "chosen_s": right["seconds"] + charge(chosen),
                        }
                    )
                row.update(
                    n=len(rows),
                    chosen_full=sum(x["chosen_full"] for x in rows),
                    baseline_full=sum(x["baseline_full"] for x in rows),
                    paired_saving_s=round(
                        sum(x["baseline_s"] - x["chosen_s"] for x in rows), 3
                    ),
                    by_seed_saving_s={
                        seed: round(
                            sum(
                                x["baseline_s"] - x["chosen_s"]
                                for x in rows
                                if x["seed"] == seed
                            ),
                            3,
                        )
                        for seed in sorted({x["seed"] for x in rows})
                    },
                )
            decisions.append(row)
    return {"development": screen, "decisions": decisions}


def prefix_sensitivity(campaigns):
    # Diagnostic after observing the original rule. Keep its training estimates
    # and vary how much first-prompt work a resident can avoid on the next job.
    by_arm = {c["arm"]: c for c in campaigns}
    resident, target = (by_arm[a] for a in ("coder", "qwen"))
    old, new = (c["trials"][0] for c in (resident, target))
    gain_needed = old["seconds"] - new["seconds"] - target["load"]
    prompt_s = old["probe"]["initial"]["prompt_ms"] / 1000
    target_cold = new["probe"]["initial"]["prompt_ms"] / 1000
    target_warm = target["trials"][1]["initial_prompt_ms"] / 1000
    return {
        "resident": "coder",
        "target": "qwen",
        "training_resident_prompt_s": round(prompt_s, 3),
        "resident_cache_saving_needed_to_stay_s": round(gain_needed, 3),
        "fraction_of_first_prompt": round(gain_needed / prompt_s, 3),
        "observed_resident_prompt_saving_s": round(
            prompt_s - resident["trials"][1]["initial_prompt_ms"] / 1000, 3
        ),
        "target_cold_minus_warm_prompt_s": round(target_cold - target_warm, 3),
    }


def retry_sensitivity(pilot, reverse=False):
    (confirm,) = [c for c in pilot["campaigns"] if "-60-confirm-" in c["run"]]
    rows = sorted(confirm["trials"], key=lambda t: t["seed"])
    if reverse:
        rows = [
            trial for i in range(0, len(rows), 2) for trial in reversed(rows[i : i + 2])
        ]
    accepted = [
        t["success"]
        and t["clean"]
        and t["within_budget"]
        and t["holdout_passed"]
        and t["handoff_accepted"]
        for t in rows
    ]
    # Disjoint adjacent pairs. Always dispatch the first; dispatch the second
    # only if the first failed. This is a simulated retry with a fresh seed.
    single_s = retried_s = 0
    first_full = retried_full = retries = 0
    for i in range(0, len(rows), 2):
        single_s += rows[i]["task_s"]
        retried_s += rows[i]["task_s"]
        first_full += accepted[i]
        if not accepted[i]:
            retries += 1
            retried_s += rows[i + 1]["task_s"]
        retried_full += accepted[i] or accepted[i + 1]
    return dict(
        total=len(rows),
        full=sum(accepted),
        rejected_seconds=round(
            sum(t["task_s"] for t, ok in zip(rows, accepted, strict=True) if not ok), 3
        ),
        first_full=first_full,
        with_retry_full=retried_full,
        pairs=len(rows) // 2,
        retries=retries,
        first_task_s=round(single_s, 3),
        with_retry_task_s=round(retried_s, 3),
    )


def main():
    evidence = read("dispatch-backtest-inputs-001.json")["campaigns"]
    report = {
        family: backtest([c for c in evidence if c["family"] == family], default)
        for family, default in (("codec", "rana"), ("release", "qwen"))
    }
    report["release_60_retry"] = retry_sensitivity(
        read("release-channel-pilot-001.json")
    )
    report["release_60_retry_reverse_pairs"] = retry_sensitivity(
        read("release-channel-pilot-001.json"), reverse=True
    )
    report["release_prefix_diagnostic"] = prefix_sensitivity(
        [c for c in evidence if c["family"] == "release"]
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
