"""Replay the sealed release-selection panel with the Lab's isolated Node runtime."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sandbox import Runtime  # noqa: E402
from verify_release_channel import verify  # noqa: E402


def stage(candidate, task, workspace):
    shutil.copytree(task / "public", workspace)
    implementation = workspace / "current-release.cjs"
    if candidate["id"] != "starter":
        shutil.copyfile(task / "private/reference/current-release.cjs", implementation)
    source = implementation.read_text()
    for edit in candidate["edits"]:
        if source.count(edit["find"]) != 1:
            raise ValueError(f"Edit no longer matches for {candidate['id']}")
        source = source.replace(edit["find"], edit["replace"])
    data = source.encode()
    if hashlib.sha256(data).hexdigest() != candidate["candidate_sha256"]:
        raise ValueError(f"Candidate differs from the sealed panel: {candidate['id']}")
    implementation.write_bytes(data)


def replay(runtime, candidate, task, output):
    workspace = output / "workspace"
    stage(candidate, task, workspace)
    public, _ = runtime.sandbox(
        workspace,
        {"mode": "grade", "argv": ["/bin/node", "tests/public.cjs"], "timeout": 8},
        output / "public",
    )
    canonical = verify(runtime, workspace, task, output, 18)
    if not canonical["allowed_paths_only"]:
        raise ValueError("Candidate exceeded the one-file scope")

    witness = candidate["witness"]
    evaluation = output / "witness-input"
    evaluation.mkdir()
    shutil.copyfile(HERE / "witness.cjs", evaluation / "observe.cjs")
    (evaluation / "input.json").write_text(
        json.dumps({key: witness[key] for key in ("records", "channel")})
    )
    observed, _ = runtime.sandbox(
        workspace,
        {
            "mode": "grade",
            "argv": ["/bin/node", "/evaluation/observe.cjs"],
            "timeout": 8,
        },
        output / "witness",
        evaluation=(evaluation, "/evaluation"),
    )
    if not observed["ok"]:
        raise ValueError(f"Witness did not finish for {candidate['id']}")
    observation = json.loads(observed["stdout"])
    value = witness["expected"]
    typed = ["object" if value is None else "number", value]
    conforms = observation["value"] == typed and observation["unchanged"] is True
    if conforms != (candidate["judgment"] == "allowed"):
        raise ValueError(
            f"Witness disagrees with the sealed judgment for {candidate['id']}"
        )
    return {
        "public": public["ok"],
        "canonical": canonical["passed"],
        "canonical_transport_ok": canonical["transport"]["ok"],
        "cases": canonical["checks"],
        "witness": observation,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="New directory for sandbox receipts and report"
    )
    parser.add_argument("--task", type=Path, default=ROOT / "tasks/release-channel")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    task = args.task.resolve()
    version = "v" + str(json.loads((task / "task.json").read_bytes())["version"])
    published = json.loads(
        (ROOT / "results/release-channel-sensitivity-001.json").read_bytes()
    )
    runtime = Runtime(node=True)
    results = {}
    for candidate in json.loads((HERE / "panel.json").read_bytes()):
        name = candidate["id"]
        row = replay(runtime, candidate, task, output / name)
        results[name] = row
        print(
            f"{name}: public={row['public']} canonical={row['canonical']}", flush=True
        )
    (output / "matrix.json").write_text(json.dumps(results, indent=2) + "\n")
    if version in published["versions"]:
        for name, row in results.items():
            expected = published["matrix"][name]
            expected_suite = expected[version]
            if (
                row["public"] != expected["public"]
                or row["canonical"] != expected_suite["passed"]
                or row["canonical_transport_ok"] != expected_suite["transport_ok"]
                or (
                    expected_suite["transport_ok"]
                    and [k for k, ok in row["cases"].items() if not ok]
                    != expected_suite["failed_cases"]
                )
            ):
                raise SystemExit(
                    f"{name} differs from the published {version} matrix; see {output}"
                )


if __name__ == "__main__":
    main()
