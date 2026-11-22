"""Replay two source-review witnesses using recorded observations or the Lab sandbox."""

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKET = HERE / "packet"
BASE = "100a7170887e79cd3d5ed87e3d054be62b18a2cc"
EXPORTER_REV = "c7b7b842d9cf7f32b4ca0b89aba04de5ee5e6421"
PYTHON_SHA = "f99ae892afc2b4b93697dc439b63369badf321b8d43222144d381852492ea9b3"
RUNS = {
    "padding": "comp55-issue-selection-worker-19550-001",
    "csv": "comp55-tabreport-diff-aider-19551-001",
}
OBJECTIONS = {
    "padding": "Converting the original decimal spelling with int() rejects a valid selection before the lookup.",
    "csv": "The LF-only CSV writer may split the quoted Team\rNorth field across records.",
}
CSV_ROWS = [
    [
        "team",
        "item",
        "kind",
        "before_minutes",
        "after_minutes",
        "before_status",
        "after_status",
        "delta_minutes",
    ],
    ["Team\rNorth", "desk", "added", "", "7", "", "open", "7"],
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def inventory(files):
    return {name: sha(data) for name, data in files.items()}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def frozen_files(directory):
    tree = f"{BASE}:{directory}"
    files = {}
    for entry in git("ls-tree", "-r", tree).decode().splitlines():
        meta, name = entry.split("\t", 1)
        mode, kind, oid = meta.split()
        if (mode, kind) != ("100644", "blob"):
            raise ValueError(f"Unexpected fixture entry: {entry}")
        files[name] = git("cat-file", "blob", oid)
    return files


def subjects(case, row):
    task = "tasks/" + row["task"]
    starter = frozen_files(task + "/public")
    overlay = {
        p.relative_to(PACKET / case / "changes")
        .as_posix()
        .removesuffix(".txt"): p.read_bytes()
        for p in (PACKET / case / "changes").rglob("*.txt")
    }
    if inventory(overlay) != row["artifact_changes"]:
        raise ValueError(f"{case}: candidate changes differ from the published #55 row")
    if case == "padding":
        path = "scripts/export_issue_context.py"
        reference = {path: git("show", f"{EXPORTER_REV}:{path}")}
    else:
        reference = frozen_files(task + "/private/reference")
    return {"candidate": starter | overlay, "reference": starter | reference}


def witness(case):
    if case == "padding":
        # The same stand-in used during #55. It records argv before servicing a lookup.
        setup = {"probe/gh": (PACKET / "padding/fake-gh.txt").read_bytes()}
        command = (
            "python -c \"import os; os.chmod('probe/gh', 0o755)\" && "
            "PATH=/workspace/probe:/bin python scripts/export_issue_context.py "
            "example/repo probe/out --issue " + "0" * 4500 + "7"
        )
        expected = {"exit": 0, "lookups": [["issue", "view", "7"]], "numbers": [7]}
    else:
        header = b"team,item,minutes,status\n"
        setup = {
            "probe/before.csv": header,
            "probe/after.csv": header + b'"Team\rNorth",desk,7,open\n',
        }
        command = "python -m tabreport.diff probe/before.csv probe/after.csv --format csv --output probe/out.csv"
        expected = {"exit": 0, "rows": CSV_ROWS, "terminator": "LF"}
    return command, setup, expected


def observation(case, gate, probe):
    result = probe.result
    if result.get("stopped_by") or type(result.get("returncode")) is not int:
        raise ValueError("Interrupted witness execution")
    observed = {"exit": result["returncode"], "stderr": result["stderr"]}
    if case == "csv":
        observed["csv_hex"] = (
            None
            if gate.absent(probe, "probe/out.csv")
            else gate.read(probe, "probe/out.csv").hex()
        )
    else:
        observed["lookups"] = (
            []
            if gate.absent(probe, "probe/calls")
            else [
                json.loads(line)[:3]
                for line in gate.read(probe, "probe/calls").splitlines()
            ]
        )
        observed["numbers"] = (
            None
            if gate.absent(probe, "probe/out")
            else [
                v["number"] for v in json.loads(gate.read(probe, "probe/out"))["issues"]
            ]
        )
    return observed


def matches(case, actual, expected):
    if case == "padding":
        return all(actual[key] == value for key, value in expected.items())
    if actual["csv_hex"] is None:
        return False
    data = bytes.fromhex(actual["csv_hex"])
    rows = list(csv.reader(io.StringIO(data.decode(), newline=""), strict=True))
    return (
        actual["exit"] == expected["exit"]
        and rows == expected["rows"]
        and data.endswith(b"\n")
        and not data.endswith(b"\r\n")
    )


def capture(runtime, output, case, role, files, command, setup):
    from behavioral_grade import Gate

    directory = output / case / role
    source = directory / "source"
    for name, data in files.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
    gate = Gate(runtime, source, directory / "gate")
    probe = gate.case(case, setup, command)
    return observation(case, gate, probe)


def check_binding(record, binding):
    if any(record[k] != v for k, v in binding.items()):
        raise ValueError("Witness capture binding differs")


def replay(output):
    history = json.loads(
        git("show", f"{BASE}:results/harness-comparison-repeats-055.json")
    )
    saved_file = PACKET / "capture.json"
    saved = json.loads(saved_file.read_bytes())
    if output:
        sys.path.insert(0, str(ROOT / "scripts"))
        from sandbox import Runtime

        runtime = Runtime()
        manifest = runtime.manifest
        runtime_id = {
            "python": manifest["tools"]["python3"],
            "python_sha256": manifest["tool_identity"]["python3"]["sha256"],
            "transport_manifest_sha256": identity(manifest),
        }
        if runtime_id["python_sha256"] != PYTHON_SHA or (
            runtime_id != saved["runtime"]
        ):
            raise ValueError("Runtime differs from the recorded pin")
        output.mkdir(parents=True, exist_ok=False)
    elif saved["runtime"]["python_sha256"] != PYTHON_SHA:
        raise ValueError("Missing capture or incorrect Python pin")
    else:
        runtime_id = saved["runtime"]

    report = {"runtime": runtime_id, "cases": {}}
    for case, run in RUNS.items():
        row = next(r for r in history["rows"] if r["run"] == run)
        original = (PACKET / case / "historical.json").read_bytes()
        key = (
            "padded_probe_sha256"
            if case == "padding"
            else "csv_roundtrip_receipt_sha256"
        )
        if sha(original) != row[key]:
            raise ValueError(f"{case}: historical receipt differs from #55")
        prior = json.loads(original)
        if prior["summary_sha256"] != row["summary_sha256"]:
            raise ValueError("Historical probe belongs to another trial")
        trees = subjects(case, row)
        command, setup, expected = witness(case)
        inputs = {
            "command": command,
            "fixtures": inventory(setup),
            "expected": expected,
        }
        records = {}
        for role, files in trees.items():
            binding = {
                "run": run,
                "role": role,
                "tree_sha256": identity(inventory(files)),
                "witness_sha256": identity(inputs),
                "runtime_sha256": identity(runtime_id),
            }
            if output:
                observed = capture(runtime, output, case, role, files, command, setup)
                records[role] = binding | {"observed": observed}
            else:
                records[role] = saved["cases"][case][role]
            check_binding(records[role], binding)
        candidate = records["candidate"]["observed"]
        reference = records["reference"]["observed"]
        if not matches(case, reference, expected):
            raise ValueError(f"{case}: reference failed the witness")
        passed = matches(case, candidate, expected)
        if passed != prior["passed"] or candidate["exit"] != prior["exit"]:
            raise ValueError(f"{case}: observation differs from historical probe")
        if case == "padding":
            if not (
                candidate["exit"] == 1
                and candidate["numbers"] is None
                and candidate["lookups"] == []
                and candidate["stderr"] == prior["stderr"]
                and "value has 4501 digits" in candidate["stderr"]
            ):
                raise ValueError(
                    "Failure did not reproduce the reported conversion error"
                )
        elif (
            candidate["csv_hex"] != prior["output_bytes"]
            or reference["csv_hex"] != history["csv_roundtrip_control"]["output_bytes"]
        ):
            raise ValueError(
                "CSV bytes differ from the original candidate or reference probe"
            )

        # Feed the reference tree through the same subject check used for a candidate.
        try:
            check_binding(
                records["candidate"],
                {"tree_sha256": identity(inventory(trees["reference"]))},
            )
        except ValueError:
            pass
        else:
            raise ValueError("Substituted reference tree was accepted as the candidate")
        report["cases"][case] = {
            "objection": OBJECTIONS[case],
            "expected": expected,
            "historical_receipt_sha256": sha(original),
            "timed_machine_pass": row["timed_machine_pass"],
            "full_reviewed_result": row["full_reviewed_result"],
            "witness_verdict": "refuted" if passed else "confirmed",
            **records,
        }
        print(
            f"{run}: {'refuted' if passed else 'confirmed'}; candidate exit {candidate['exit']}, "
            f"reference exit {reference['exit']}; substituted tree rejected"
        )
    if output:
        (output / "capture.json").write_text(json.dumps(report, indent=2) + "\n")
    if report != saved:
        raise ValueError("Replay differs from the published capture")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture",
        type=Path,
        metavar="NEW_DIRECTORY",
        help="execute both pairs using the pinned isolated Lab runtime",
    )
    replay(parser.parse_args().capture)
