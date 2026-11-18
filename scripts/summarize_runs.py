"""Read preserved campaign evidence; never run candidate code or mutate a run."""

import argparse
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path("/bulk/dlk/local-harness/runs")


def summarize(root):
    root = root.resolve()
    if not root.is_relative_to(ROOT) or not root.is_dir():
        raise ValueError("Expected an existing campaign under project bulk runs")
    evidence = {}

    def read(relative):
        path = root / relative
        if not path.exists():
            return {}
        raw = path.read_bytes()
        evidence[relative] = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        return json.loads(raw)

    experiment = read("experiment/summary.json")
    background = read("background/summary.json")
    voice = read("voice/result.json")
    ollama = read("ollama/result.json")
    inputs = read("inputs.json")
    trials = []
    for path in sorted((root / "experiment").glob("trial-*/summary.json")):
        data = read(str(path.relative_to(root)))
        row = {
            name: data.get(name)
            for name in (
                "task",
                "seed",
                "split",
                "model",
                "success",
                "canonical_correctness",
                "delivery_correctness",
                "clean_agent_completion",
                "human_interventions",
                "within_budget",
                "task_wall_seconds",
                "agent_wall_seconds",
                "verification_wall_seconds",
                "agent_error",
                "verification_error",
                "usage",
                "tool_calls",
            )
        }
        row["path"] = str(path.parent)
        row["protocol"] = data.get("limits", {}).get("protocol")
        trajectory = read(str(path.with_name("trajectory.json").relative_to(root)))
        row["exit_status"] = trajectory.get("info", {}).get("exit_status")
        row["fixture_sha256"] = data.get("fixture", {}).get("sha256")
        row["tests"] = {
            k: v
            for k, v in data.get("verification", {}).get("tests", {}).items()
            if k != "log"
        }
        row["parent_process_wall_seconds"] = next(
            (
                t["process_wall_seconds"]
                for t in experiment.get("trials", [])
                if t["path"] == str(path.parent)
            ),
            None,
        )
        trials.append(row)
    return {
        "campaign": root.name,
        "path": str(root),
        "profile": experiment.get("profile"),
        "inputs_sha256": inputs.get("sha256"),
        "experiment_completed": experiment.get("completed", False),
        "server_stopped": experiment.get("server_stopped"),
        "client_stopped": experiment.get("client_stopped"),
        "weight_verification_seconds": experiment.get("weight_verification_seconds"),
        "model_load_seconds": experiment.get("model_load_seconds"),
        "lifecycle": {
            "background_restored": background.get("restored"),
            "voice_states_verified": voice.get("states_verified"),
            "ollama_restoration_verified": ollama.get("restoration_verified"),
            "ollama_service_unchanged": ollama.get("service_unchanged"),
            "ollama_mutation_attempted": ollama.get("mutation_attempted"),
            "background_error": background.get("error"),
            "voice_error": voice.get("error"),
            "experiment_error": experiment.get("error"),
        },
        "trials": trials,
        "evidence": evidence,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaigns", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = {
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "limitations": [
            "Tiny authored development tasks; no general quality ranking or latency distribution.",
            "Warm ready server; prefix caching enabled across requests and tasks.",
            "v0 task clock excludes startup/freezing; use its parent process time.",
            "Missing fields mean absent evidence, not successful restoration.",
            "Canonical tests and candidate share a host-isolated process; not adversarial scoring.",
        ],
        "campaigns": [summarize(path) for path in args.campaigns],
    }
    if args.report:
        with args.report.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    for campaign in report["campaigns"]:
        print(campaign["campaign"])
        if not campaign["trials"]:
            print("  No task result; inspect lifecycle evidence.")
        for trial in campaign["trials"]:
            print(
                f"  {trial['task']:16} success={str(trial['success']):5} "
                f"correct={str(trial['canonical_correctness']):5} "
                f"clean={str(trial['clean_agent_completion']):5} "
                f"task={trial['task_wall_seconds']:.2f}s"
            )


if __name__ == "__main__":
    main()
