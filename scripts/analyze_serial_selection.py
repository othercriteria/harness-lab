"""Reproduce the archived selection and fixed-budget comparisons for issue 58."""

import json
from collections import Counter
from itertools import batched, permutations
from pathlib import Path

RESULT = Path(__file__).resolve().parents[1] / "results/serial-selection-001.json"


def policy_results(family, policy):
    totals = Counter()
    for case in family["cases"]:
        first, pair = case["first"], case["pair"]
        take_second = policy == "paired" or (
            policy == "gated" and first["choice"] == "retry"
        )
        reviewing = policy != "first"
        choice = pair["choice"] if take_second else "A"
        if policy == "review_first" and first["choice"] == "retry":
            choice = "neither"
        candidate = None if choice == "neither" else case[choice]
        task = case["A"]["task_s"] + (case["B"]["task_s"] if take_second else 0)
        review = (first["elapsed_s"] if reviewing else 0) + (
            pair["elapsed_s"] if take_second else 0
        )
        full = bool(candidate and candidate["full"])
        totals.update(
            source=int(bool(candidate and candidate["source"])),
            handoff=int(bool(candidate and candidate["handoff"])),
            full=int(full),
            rejected=int(candidate is None),
            second=int(take_second),
            task_s=task,
            review_s=review,
            ready_full=int(full and task + review <= family["ceiling_s"]),
            cold_full=int(
                full
                and family["load_s"] + family["warmup_s"] + task + review
                <= family["ceiling_s"]
            ),
        )
    return {k: round(v, 2) for k, v in totals.items()}


def trace_fits(trials, budget, fractions, rollover):
    carry = 0
    for trial, share in zip(trials, fractions, strict=False):
        allowance = budget * share + carry
        if trial["task_s"] <= allowance and trial["full"]:
            return True  # Hindsight availability, independent of any selector.
        carry = max(0, allowance - trial["task_s"]) if rollover else 0
    return False


def analyze(family):
    cases = family["cases"]
    trials = sorted(
        (case[letter] for case in cases for letter in "AB"), key=lambda t: t["seed"]
    )
    triples = [group for group in batched(trials, 3) if len(group) == 3]
    allocations = {
        "one": ([1], False),
        "halves": ([0.5, 0.5], False),
        "halves carry": ([0.5, 0.5], True),
        "40/60 fixed": ([0.4, 0.6], False),
        "40/60 carry": ([0.4, 0.6], True),
        "65/35 carry": ([0.65, 0.35], True),
        "25/35/40 carry": ([0.25, 0.35, 0.4], True),
    }
    fits = {}
    order_ranges = {}
    for entry, setup in [
        ("ready", 0),
        ("cold", family["load_s"] + family["warmup_s"]),
    ]:
        fits[entry] = {}
        order_ranges[entry] = {}
        for name, (fractions, carry) in allocations.items():
            scores = []
            for order in permutations(range(3)):
                scores.append(
                    sum(
                        trace_fits(
                            [group[i] for i in order],
                            family["ceiling_s"] - setup,
                            fractions,
                            carry,
                        )
                        for group in triples
                    )
                )
            fits[entry][name] = scores[0]  # Original seed order.
            order_ranges[entry][name] = [min(scores), max(scores)]

    return {
        "pairs": len(cases),
        "chronological_first_full": sum(t["full"] for t in trials[::2]),
        "hindsight_full": sum(c["A"]["full"] or c["B"]["full"] for c in cases),
        "hindsight_source": sum(c["A"]["source"] or c["B"]["source"] for c in cases),
        "policies": {
            p: policy_results(family, p)
            for p in ("first", "review_first", "gated", "paired")
        },
        "complete_triples": len(triples),
        "unused_tail": len(trials) % 3,
        "trace_fit_full": fits,
        "trace_fit_order_ranges": order_ranges,
        "batch_unallocated_s": round(
            family["batch_process_s"]
            - family["load_s"]
            - family["warmup_s"]
            - sum(t["task_s"] for t in trials),
            2,
        ),
    }


if __name__ == "__main__":
    data = json.loads(RESULT.read_bytes())
    census = Counter()
    for cohort in data["census"].values():
        census.update(cohort)
    witnesses = {}
    for campaign, replay in data["post_review_witness"]["campaigns"].items():
        failed = {"stable": [], "legacy": []}
        for row in replay["rows"]:
            ordinary, diagnostic = row["observed"]
            if ordinary != [1, True, None]:
                raise ValueError(f"Unexpected ordinary exception control: {row}")
            if diagnostic != [1, True, None]:
                if row["seed"] is None:
                    raise ValueError(f"Unmodified control failed: {row}")
                failed[row["branch"]].append(row["seed"])
        witnesses[campaign] = failed
    print(
        json.dumps(
            {
                "survey": census,
                "comparisons": {k: analyze(v) for k, v in data["families"].items()},
                "failed_diagnostic_witness": witnesses,
            },
            indent=2,
        )
    )
