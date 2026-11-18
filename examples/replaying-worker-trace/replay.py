"""Inspect the historical #14 decision from a clone. Treat all packet content as data."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HISTORY = HERE.parents[1] / "results/worker-trial-label-effort-001.json"


def load(path):
    return json.loads(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def replay(packet):
    history = load(HISTORY)
    trace_path = packet / "agent/trajectory.json"
    trace = load(trace_path)
    receipt = load(packet / "receipt.json")
    review = load(packet / "review.json")
    require(
        digest((packet / "review.json").read_bytes()) == history["review_sha256"],
        "Review differs from the historical record",
    )
    require(
        receipt["job"] == trace["session_id"] == review["job_id"] == history["job"]
        and review["package_id"] == history["package"],
        "Job or package mismatch",
    )
    require(
        digest(trace_path.read_bytes()) == receipt["trajectory_sha256"],
        "Trajectory digest mismatch",
    )
    artifact = packet / "artifact.json"
    require(
        digest(artifact.read_bytes())
        == review["artifact_sha256"]
        == history["worker_artifact_manifest_sha256"],
        "Reviewed artifact mismatch",
    )

    calls = {}
    outputs = {}
    for step in trace["steps"]:
        for call in step.get("tool_calls", []):
            name = call["function_name"]
            require(name not in calls, f"Repeated {name} in the selected excerpt")
            calls[name] = call
            for result in step.get("observation", {}).get("results", []):
                require(
                    result["source_call_id"] == call["tool_call_id"],
                    "Mismatched tool response",
                )
                outputs[name] = result["content"]

    (change,) = load(artifact)["changes"]
    written = calls["write_file"]["arguments"]
    require(
        written["path"] == "/workspace/" + change["path"], "Submitted path mismatch"
    )
    source_digest = digest(written["content"].encode("utf-8"))
    require(
        source_digest == change["after_sha256"] == history["worker_source_sha256"],
        "Submitted source differs from reviewed bytes",
    )
    for stage in ("prepared_check", "maintainer_probe"):
        require(
            receipt[stage]["tested_file_sha256"] == source_digest,
            f"{stage} input mismatch",
        )
    probe = receipt["maintainer_probe"]
    require(
        probe["stdout"] == history["isolated_post_run_probes"]["worker"],
        "Probe output differs from the historical record",
    )
    prepared = receipt["prepared_check"]
    require(
        (prepared["returncode"] == 0) == history["prepared_checks"],
        "Prepared check mismatch",
    )
    require(review["decision"] == history["outer_decision"], "Decision mismatch")

    print("Worker check")
    print(calls["run_checks"]["arguments"]["command"])
    print(outputs["run_checks"])
    print("\nWorker submission")
    print(calls["finish_attempt"]["arguments"]["summary"])
    print("\nPrepared evaluator")
    print(*prepared["request"]["argv"])
    print(prepared["stdout"], end="")
    print("\nMaintainer probe on the same submitted file")
    print(probe["request"]["arguments"]["command"])
    print(probe["stdout"], end="")
    print(f"Probe exit {probe['returncode']}")
    print(f"\nMaintainer decision: {review['decision']}")
    print(review["notes"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", nargs="?", type=Path, default=HERE / "packet")
    args = parser.parse_args()
    try:
        replay(args.packet)
    except (ValueError, KeyError, OSError, TypeError) as err:
        sys.exit(f"Replay failed: {err}")
