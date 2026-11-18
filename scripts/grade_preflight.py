"""Supplemental source-readability and path-access checks for aligned build tasks.

This probes an explicit public preflight obligation. Candidate code and the
driver execute only in Gate's sandbox; verdicts remain in this controller.
"""

DRIVER = b"""import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace")
from buildflow.planner import plan
from buildflow.runner import run
root = Path("/workspace/probe/root")
root.mkdir(parents=True)
(root / "good").write_text("readable")
(root / "denied").write_text("unreadable")
(root / "denied").chmod(0)
observed = {}
try:
    (root / "denied").read_bytes()
    observed["permission_control"] = "readable"
except Exception as exc:
    observed["permission_control"] = type(exc).__name__
spec = {"version": 1, "steps": [
    {"id": "a", "command": ["make"], "inputs": ["good"], "outputs": ["generated"]},
    {"id": "b", "command": ["use"], "deps": ["a"],
     "inputs": ["generated", "denied"], "outputs": ["result"]},
]}
try:
    plan(spec, root)
    observed["plan_error"] = None
except Exception as exc:
    observed["plan_error"] = type(exc).__name__
calls = []
def execute(name, command):
    calls.append(name)
    (root / ("generated" if name == "a" else "result")).write_text("created")
    return 0
try:
    run(spec, root, execute)
    observed["run_error"] = None
except Exception as exc:
    observed["run_error"] = type(exc).__name__
observed["calls"] = calls
(root / "denied").chmod(0o600)
print(json.dumps(observed))
"""

PATH_ACCESS_DRIVER = b"""import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace")
from buildflow.planner import plan
from buildflow.runner import run
root = Path("/workspace/probe/root")
root.mkdir()
(root / "out").mkdir()
(root / "out/value").write_text("existing")
(root / "out").chmod(0)
observed, calls = {}, []
spec = {"version": 1, "steps": [
    {"id": "build", "command": ["make"], "outputs": ["out/value"]},
]}
def execute(name, command):
    calls.append(name)
    return 0
try:
    try:
        (root / "out/value").stat()
        observed["permission_control"] = "accessible"
    except OSError as exc:
        observed["permission_control"] = type(exc).__name__
    for name, action in (("plan", lambda: plan(spec, root)),
                         ("run", lambda: run(spec, root, execute))):
        try:
            action()
            observed[name + "_error"] = None
        except Exception as exc:
            observed[name + "_error"] = type(exc).__name__
    observed["calls"] = calls
finally:
    (root / "out").chmod(0o700)
print(json.dumps(observed))
"""


def check_path_access(gate, *, require_plan):
    probe = gate.case(
        "existing-output-path-access",
        {"probe/driver.py": PATH_ACCESS_DRIVER},
        "python -I -S probe/driver.py",
    )
    try:
        observed = gate.json(probe)
    except (ValueError, TypeError):
        observed = None
    valid = (
        probe.result.get("ok") is True
        and probe.result.get("returncode") == 0
        and probe.result.get("stderr") == ""
        and isinstance(observed, dict)
        and observed.get("permission_control") == "PermissionError"
    )
    details = {"observed": observed, "transport": probe.result}
    gate.record("output-access-permission-control", valid, details)
    # Require the public ordering guarantee, not a particular implementation
    # (e.g. lstat's PermissionError versus an earlier explicit access check).
    gate.record(
        "output-access-before-run-callbacks",
        valid
        and isinstance(observed.get("run_error"), str)
        and bool(observed["run_error"])
        and observed.get("calls") == [],
        details,
    )
    if require_plan:
        gate.record(
            "output-access-before-returning-plan",
            valid
            and isinstance(observed.get("plan_error"), str)
            and bool(observed["plan_error"]),
            details,
        )


def check(gate, *, require_plan):
    probe = gate.case(
        "ordinary-source-readability",
        {"probe/driver.py": DRIVER},
        "python -I -S probe/driver.py",
    )
    try:
        observed = gate.json(probe)
    except (ValueError, TypeError):
        observed = None
    valid = (
        probe.result.get("ok") is True
        and probe.result.get("stderr") == ""
        and isinstance(observed, dict)
        and observed.get("permission_control") == "PermissionError"
    )
    details = {"observed": observed, "transport": probe.result}
    gate.record("readability-permission-control", valid, details)
    # Test the ordering obligation without prescribing how readability is
    # checked (for example, opening the source versus checking access first).
    gate.record(
        "readability-before-run-callbacks",
        valid
        and isinstance(observed.get("run_error"), str)
        and bool(observed["run_error"])
        and observed.get("calls") == [],
        details,
    )
    if require_plan:
        gate.record(
            "readability-before-returning-plan",
            valid
            and isinstance(observed.get("plan_error"), str)
            and bool(observed["plan_error"]),
            details,
        )
    check_path_access(gate, require_plan=require_plan)
