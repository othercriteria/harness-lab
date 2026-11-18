"""Rebuild the selected #14 evidence in a new directory from the historical archive."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

JOB = "bdd9d9cfa7af49629387fff596dccdbf"
SUBMISSION = "scripts/observe_review.py"
# Native assistant turns. The two read_file calls in turn 2 share one turn.
SELECTED = {4: "write_file", 6: "bash", 7: "run_checks", 9: "finish_attempt"}


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def project(native, trial):
    messages = native["messages"]
    (user,) = (m for m in messages if m["role"] == "user")
    steps = [dict(step_id=1, source="user", message=user["content"])]
    turns = [index for index, m in enumerate(messages) if m["role"] == "assistant"]
    for turn, name in SELECTED.items():
        index = turns[turn - 1]
        message = messages[index]
        (call,) = message["tool_calls"]
        if call["function"]["name"] != name:
            raise ValueError(f"Unexpected action at native turn {turn}")
        identifier = call["id"]
        step = dict(
            step_id=len(steps) + 1,
            source="agent",
            message=message["content"],
            tool_calls=[
                dict(
                    tool_call_id=identifier,
                    function_name=name,
                    arguments=json.loads(call["function"]["arguments"]),
                )
            ],
            extra={"worker_assistant_turn": turn},
        )
        following = messages[index + 1]
        if name == "finish_attempt":
            if following["role"] != "exit" or following["content"] != "Submitted":
                raise ValueError("Expected a terminal submission")
        else:
            if following["role"] != "tool" or following["tool_call_id"] != identifier:
                raise ValueError(f"Missing paired observation at turn {turn}")
            step["observation"] = {
                "results": [
                    dict(source_call_id=identifier, content=following["content"])
                ]
            }
        steps.append(step)
    summary = load(trial / "summary.json")
    return dict(
        schema_version="ATIF-v1.8",
        session_id=JOB,
        agent=dict(
            name="Local Harness Lab Worker",
            version="run_trial.py@sha256:" + summary["agent_source_sha256"],
            model_name=native["info"]["local_model"]["model"],
        ),
        steps=steps,
        extra=dict(
            scope="Selected historical interactions for offline inspection",
            native_format=native["trajectory_format"],
            native_assistant_turns=len(turns),
        ),
    )


def check_record(request, result, tested_source):
    observed = load(result)
    return dict(
        request=load(request),
        returncode=observed["returncode"],
        stdout=observed["stdout"],
        stderr=observed["stderr"],
        tested_file_sha256=sha(tested_source),
    )


def export(bulk, dest):
    job = bulk / "delegation/jobs" / JOB
    trial = bulk / "runs" / f"delegate-{JOB}" / "experiment/trial-00-delegated-task"
    probe = bulk / "research/worker-trial-label-001/verify-worker"
    trace = project(load(trial / "trajectory.json"), trial)
    prepared = check_record(
        trial / "delegated-check-00.request.json",
        trial / "delegated-check-00.result.json",
        trial / "delegated-candidate" / SUBMISSION,
    )
    independent = check_record(
        probe / "probe.request.json",
        probe / "probe.result.json",
        probe / "workspace/observe_review.py",
    )
    artifact = job / "artifact/artifact.json"
    review = job / "review.json"
    if sha(artifact) != load(review)["artifact_sha256"]:
        raise ValueError("Review refers to a different artifact")
    expected = sha(job / "artifact/files" / SUBMISSION)
    if {prepared["tested_file_sha256"], independent["tested_file_sha256"]} != {
        expected
    }:
        raise ValueError("Checks ran on different source bytes")
    dest.mkdir()
    (dest / "agent").mkdir()
    trajectory = dest / "agent/trajectory.json"
    save(trajectory, trace)
    shutil.copyfile(artifact, dest / "artifact.json")
    shutil.copyfile(review, dest / "review.json")
    save(
        dest / "receipt.json",
        dict(
            job=JOB,
            trajectory_sha256=sha(trajectory),
            prepared_check=prepared,
            maintainer_probe=independent,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bulk", type=Path)
    parser.add_argument("new_directory", type=Path)
    args = parser.parse_args()
    export(args.bulk, args.new_directory)
