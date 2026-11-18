"""Rebuild the #19 timing study from outer receipts. Reads no model output."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median


def read(path):
    return json.loads(path.read_bytes())


def epoch(timestamp):
    return datetime.fromisoformat(timestamp).timestamp()


def server_key(experiment):
    profile = read(experiment / "profile.json")
    launch = read(experiment / "launch.json")
    argv = launch["argv"].copy()
    argv[argv.index("--port") + 1] = "<ephemeral>"
    data = [profile, launch["binary_sha256"], argv]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def job_row(root, path, state):
    job = path.parent
    run = root / "runs" / ("delegate-" + job.name)
    experiment = run / "experiment"
    request = read(job / "request.json")
    summary = read(experiment / "summary.json")
    ollama = read(run / "ollama/result.json")
    entry_models = read(next((run / "ollama").glob("*-ps-before.json")))["response"][
        "models"
    ]
    if bool(entry_models) != ollama["mutation_attempted"] or (
        entry_models and ollama.get("restoration_verified") is not True
    ):
        raise ValueError(f"Unreconciled entry-state receipt in {job.name}")
    row = {
        "id": job.name,
        "session": request["session_id"],
        "kind": read(job / "classification.json")["kind"]
        if (job / "classification.json").exists()
        else "unclassified",
        "package_id": request["package_id"],
        "submitted": state["submitted_at"],
        "completed": state.get("completed_at"),
        "profile": summary["profile"],
        "dispatch": state.get("dispatch_seconds"),
        "load": summary.get("model_load_seconds"),
        "cleanup_verified": state.get("cleanup_verified"),
        "other_model_displaced": bool(entry_models),
        "server_key": server_key(experiment),
    }
    trials = list(experiment.glob("trial-*/summary.json"))
    if row["dispatch"] is None or row["load"] is None or len(trials) != 1:
        return row
    trial = read(trials[0])
    if (
        trial.get("agent_wall_seconds") is None
        or trial.get("verification_wall_seconds") is None
    ):
        return row
    timings = list(trials[0].parent.glob("request-[0-9]*.timing.json"))
    request_seconds = sum(read(f)["wall_seconds"] for f in timings)
    # A timed request is observed client wait, including HTTP overhead.
    warm = summary.get("prefix_warmup", {}).get("process_wall_seconds", 0)
    tail = epoch(row["completed"]) - summary["resources_after"]["time"]
    components = {
        "load_to_ready": row["load"],
        "discarded_prefix_warmup": warm,
        "timed_model_requests": request_seconds,
        "agent_other_or_untimed": trial["agent_wall_seconds"] - request_seconds,
        "verification": trial["verification_wall_seconds"],
        "post_server_cleanup_and_restoration": tail,
    }
    components["other_dispatch"] = row["dispatch"] - sum(components.values())
    if min(components.values()) < 0:
        raise ValueError(f"Inconsistent clocks or overlapping phases in {job.name}")
    row["seconds"] = components
    # Older wrappers have no timestamped idle check. Leave those durations unknown.
    starts = sorted((run / "ollama").glob("*-connections-before-restore-*-*.json"))
    responses = sorted((run / "ollama").glob("*-restore-response-*.json"))
    if starts and responses:
        start = read(starts[0]).get("at")
        end = read(responses[-1]).get("created_at")
        if start and end:
            row["ollama_restore_interval"] = epoch(end) - epoch(start)
    return row


def phases(rows):
    return {
        "jobs": len(rows),
        "total_dispatch_seconds": round(sum(r["dispatch"] for r in rows), 2),
        "seconds": {
            k: round(sum(r["seconds"][k] for r in rows), 2) for k in rows[0]["seconds"]
        },
        "median_load_seconds": round(median(r["load"] for r in rows), 2),
    }


def opportunity(rows, other_starts, gap_limit):
    links = []
    for a, b in zip(rows, rows[1:]):
        if not all(r.get("seconds") and r["cleanup_verified"] for r in (a, b)):
            continue
        if a["session"] != b["session"] or a["server_key"] != b["server_key"]:
            continue
        end, start = epoch(a["completed"]), epoch(b["submitted"])
        if not 0 <= start - end <= gap_limit or any(
            end <= t <= start for t in other_starts
        ):
            continue
        links.append((a, b, start - end))
    return links


def price(links):
    involved = {r["id"]: r for a, b, _ in links for r in (a, b)}
    return {
        "links": len(links),
        "sessions": len({b["session"] for _, b, _ in links}),
        "batches": len(involved) - len(links),
        "jobs_in_batches": len(involved),
        "dispatch_seconds_in_batches": round(
            sum(r["dispatch"] for r in involved.values()), 2
        ),
        "later_load_seconds": round(sum(b["load"] for _, b, _ in links), 2),
        "inter_job_gap_seconds": round(sum(g for _, _, g in links), 2),
        "links_with_displacement_on_either_job": sum(
            a["other_model_displaced"] or b["other_model_displaced"]
            for a, b, _ in links
        ),
    }


def study(root, cutoff):
    rows = []
    for path in (root / "delegation/jobs").glob("*/state.json"):
        state = read(path)
        if epoch(state["submitted_at"]) < epoch(cutoff):
            rows.append(job_row(root, path, state))
    rows.sort(key=lambda r: epoch(r["submitted"]))
    first, last = epoch(rows[0]["submitted"]), epoch(cutoff)
    other = []
    other_wall = 0
    for path in (root / "runs").glob("*/experiment/resources-before.json"):
        if path.parents[1].name.startswith("delegate-"):
            continue
        start = read(path)["time"]
        if first <= start < last:
            other.append(start)
            end = read(path.with_name("summary.json"))["resources_after"]["time"]
            other_wall += min(end, last) - start
    measured = [r for r in rows if "seconds" in r]
    profiles = sorted({r["profile"] for r in measured})
    links = opportunity(rows, other, 10)
    restored = [
        r["ollama_restore_interval"] for r in measured if "ollama_restore_interval" in r
    ]
    # The last ten Worker sessions form a recent-use sensitivity check.
    recent = list(dict.fromkeys(r["session"] for r in rows))[-10:]
    recent_rows = [r for r in rows if r["session"] in recent]
    session_sizes = Counter(r["session"] for r in rows)
    by_kind = defaultdict(list)
    for row in rows:
        by_kind[row["kind"]].append(row)
    samples = {}
    for name, session, profile in [
        ("coder_issue_23", "047", "routing-coder-32k-cpu31-fit1536-temp06"),
        (
            "qwen_checkpoint_screen",
            "032",
            "qwen38-27b-ranalayout-32k-temp06-dflash3-fit2304-dio",
        ),
        (
            "qwen_issue_advice_singleton",
            "048",
            "qwen38-27b-ranalayout-32k-temp06-dflash3-fit2304-dio",
        ),
    ]:
        sample = [
            r
            for r in measured
            if r["session"].endswith("-" + session) and r["profile"] == profile
        ]
        samples[name] = {
            "jobs": [
                {
                    "id": r["id"],
                    "dispatch": round(r["dispatch"], 2),
                    "seconds": {k: round(v, 2) for k, v in r["seconds"].items()},
                }
                for r in sample
            ],
            "phases": phases(sample),
            "ten_second_links": price(
                [s for s in links if s[1] in sample and s[0] in sample]
            ),
        }
    return {
        "cutoff_utc_exclusive": cutoff,
        "first_submission": rows[0]["submitted"],
        "jobs_seen": len(rows),
        "sessions": len({r["session"] for r in rows}),
        "incomplete_phase_jobs": [r["id"] for r in rows if "seconds" not in r],
        "all_measured": phases(measured),
        "by_profile": {
            p: phases([r for r in measured if r["profile"] == p]) for p in profiles
        },
        "other_recorded_experiments": {
            "starts": len(other),
            "server_owner_wall_seconds": round(other_wall, 2),
        },
        "classified_demand": {
            k: {
                "jobs": len(group),
                "in_single_job_session": sum(
                    session_sizes[r["session"]] == 1 for r in group
                ),
                "later_jobs_in_ten_second_links": sum(
                    b["kind"] == k for _, b, _ in links
                ),
            }
            for k, group in sorted(by_kind.items())
        },
        "ten_second_links_without_displacement": price(
            [s for s in links if not any(r["other_model_displaced"] for r in s[:2])]
        ),
        "ten_second_same_package_links": price(
            [s for s in links if s[0]["package_id"] == s[1]["package_id"]]
        ),
        "entry_model_displaced_jobs": sum(r["other_model_displaced"] for r in rows),
        "timestamped_ollama_restore": {
            "jobs": len(restored),
            "median_seconds": round(median(restored), 2),
        },
        "gap_sensitivity_seconds": {
            str(g): price(opportunity(rows, other, g)) for g in (2, 5, 10, 30, 60)
        },
        "ten_second_links_by_profile": {
            p: price([s for s in links if s[1]["profile"] == p]) for p in profiles
        },
        "recent_ten_sessions": {
            "sessions": recent,
            "jobs": len(recent_rows),
            "single_job_sessions": sum(
                v == 1 for v in Counter(r["session"] for r in recent_rows).values()
            ),
            "phases": phases([r for r in recent_rows if "seconds" in r]),
            "ten_second_links": price(opportunity(recent_rows, other, 10)),
        },
        "samples": samples,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk", type=Path, default=Path("/bulk/dlk/local-harness"))
    parser.add_argument("--before", default="2026-11-18T19:20:00+00:00")
    args = parser.parse_args()
    print(json.dumps(study(args.bulk, args.before), indent=2))
