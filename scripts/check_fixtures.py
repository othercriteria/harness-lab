"""Validate authored fixtures locally and admitted imports only in sandboxes.

The legacy host path accepts trusted authored baselines/references only. Imported
fixtures dispatch before that path; unsupported imports fail closed. Never pass
model submissions to this development checker.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from protocol import requires_outer_adjudication

ROOT = Path(__file__).resolve().parents[1]
SUITE_RUNNER = r"""
import io, json, sys, unittest
sys.path.insert(0, sys.argv[1])
suite = unittest.defaultTestLoader.discover(sys.argv[2], pattern='test_*.py')
output = io.StringIO()
result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
print(json.dumps({
    'passed': result.wasSuccessful() and result.testsRun > 0,
    'tests_run': result.testsRun,
    'failures': len(result.failures),
    'errors': len(result.errors),
    'skipped': len(result.skipped),
    'log': output.getvalue(),
}))
"""


def manifest(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError(f"Symlink in fixture: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": files}


def run_suite(workspace, suite):
    started = time.monotonic()
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                SUITE_RUNNER,
                str(workspace),
                str(suite),
            ],
            cwd=workspace,
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "status": "timeout",
            "wall_seconds": time.monotonic() - started,
        }
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError:
        result = {
            "passed": False,
            "status": "invalid_report",
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    if process.returncode:
        result["passed"] = False
        result["status"] = "runner_error"
        result["stderr"] = process.stderr
    result["returncode"] = process.returncode
    result["wall_seconds"] = time.monotonic() - started
    return result


def check_task(task):
    metadata = json.loads((task / "task.json").read_text())
    if requires_outer_adjudication(metadata):
        raise ValueError(
            "Outer-adjudicated fixture: use isolated triage admission; host execution refused"
        )
    if metadata.get("fixture_validation") == "isolated-only":
        raise ValueError("This fixture requires isolated validation; host reference execution refused")
    origin = metadata.get("origin", "authored")
    if origin not in {"authored", "imported"}:
        raise ValueError("Unknown fixture origin; refusing host execution")
    if origin == "imported" or "upstream" in metadata or "evaluator" in metadata:
        raise ValueError("Imported fixtures require a separate isolated evaluator")
    before = manifest(task)
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="local-harness-fixture-") as directory:
        scratch = Path(directory)
        for variant in ("baseline", "reference"):
            workspace = scratch / variant
            shutil.copytree(
                task / "public", workspace, ignore=shutil.ignore_patterns("__pycache__")
            )
            if variant == "reference":
                shutil.copytree(
                    task / "private/reference",
                    workspace,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            # Read canonical test files, not the workspace's mutable tests.
            outcomes[variant] = {
                "public": run_suite(workspace, task / "public/tests"),
                "acceptance": run_suite(workspace, task / "private"),
            }
    metadata = json.loads((task / "task.json").read_text())
    expected_counts = metadata["test_counts"]
    baseline_public_passes = metadata.get("baseline_public_passes", True)
    if type(baseline_public_passes) is not bool:
        raise ValueError("baseline_public_passes must be a boolean")
    reports_valid = all(
        "status" not in outcome
        and outcome.get("tests_run") == expected_counts[suite]
        and outcome.get("skipped") == 0
        for variants in outcomes.values()
        for suite, outcome in variants.items()
    )
    stable = before == manifest(task)
    valid = (
        reports_valid
        and stable
        and outcomes["baseline"]["public"]["passed"] is baseline_public_passes
        and not outcomes["baseline"]["acceptance"]["passed"]
        and outcomes["reference"]["public"]["passed"]
        and outcomes["reference"]["acceptance"]["passed"]
    )
    return {
        "task": task.name,
        "valid": valid,
        "inputs_unchanged": stable,
        "baseline_public_passes_expected": baseline_public_passes,
        "fixture": before,
        "outcomes": outcomes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="New JSON report path")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("report already exists; use a fresh path")
    tasks = [check_task(p.parent) for p in sorted((ROOT / "tasks").glob("*/task.json"))]
    report = {
        "schema_version": 1,
        "kind": "trusted-fixture-validation",
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "python": sys.version,
        "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "passed": all(task["valid"] for task in tasks),
        "tasks": tasks,
        "limitations": [
            "No model ran",
            "Authored fixtures use a trusted host path; imported fixtures use sandboxes",
            "Does not establish hidden-test completeness",
        ],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    for task in tasks:
        print(f"{task['task']}: {'PASS' if task['valid'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
