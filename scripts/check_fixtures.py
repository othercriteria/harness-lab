"""Run public and acceptance suites for trusted authored baselines and references.

Imported, isolated-only and outer-adjudicated fixtures need separate evaluation.
Never pass model submissions to this development checker.
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


def separate_evaluation(metadata):
    """Classify declared evaluation boundaries before opening fixture source."""
    outer = requires_outer_adjudication(metadata)
    if metadata.get("origin", "authored") not in {"authored", "imported"}:
        raise ValueError("Unknown fixture origin; refusing host execution")
    if metadata.get("fixture_validation") not in (None, "isolated-only"):
        raise ValueError("Unknown fixture validation mode; refusing host execution")
    if outer:
        return "outer adjudication"
    if metadata.get("fixture_validation") == "isolated-only":
        return "isolated-only validation"
    if (
        metadata.get("origin") == "imported"
        or "upstream" in metadata
        or "evaluator" in metadata
    ):
        return "separate isolated evaluator"
    return None


def check_task(task):
    metadata = json.loads((task / "task.json").read_text())
    reason = separate_evaluation(metadata)
    if reason:
        raise ValueError(f"{task.name} requires {reason}; host execution refused")
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
    parser.add_argument(
        "--host-eligible",
        action="store_true",
        help="Validate host-eligible authored fixtures and list tasks requiring separate evaluation",
    )
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("report already exists; use a fresh path")
    tasks = []
    deferred = {}
    for path in sorted((ROOT / "tasks").glob("*/task.json")):
        task = path.parent
        if args.host_eligible:
            reason = separate_evaluation(json.loads(path.read_text()))
            if reason:
                deferred[task.name] = reason
                continue
        tasks.append(check_task(task))
    report = {
        "schema_version": 1,
        "kind": "trusted-fixture-validation",
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "python": sys.version,
        "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "passed": bool(tasks) and all(task["valid"] for task in tasks),
        "requires_separate_evaluation": deferred,
        "tasks": tasks,
        "limitations": [
            "No model ran",
            "Only host-eligible trusted authored fixtures ran",
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
    for name, reason in deferred.items():
        print(f"{name}: NOT RUN ({reason})")
    print(
        f"Validated {sum(task['valid'] for task in tasks)} of {len(tasks)} host fixtures; "
        f"{len(deferred)} require separate evaluation."
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
