"""Post-command artifact path checks; candidate code runs only inside Gate.

A command can create a previously absent path component. Preflight alone cannot
establish that the resulting output has no symlink components. Raw API output is
still untrusted; outer comparisons supplement, not prove, adversarial correctness.
"""

DRIVER = b"""import json, sys
from pathlib import Path

sys.path.insert(0, "/workspace")
from buildflow.runner import run

observations = {}
for kind in ["ordinary", "parent_symlink", "leaf_symlink"]:
    root = Path("/workspace/probe") / kind
    root.mkdir()
    (root / "real").mkdir()
    (root / "real/value").write_bytes(b"content")
    spec = {
        "version": 1,
        "steps": [{"id": "build", "command": ["make"], "outputs": ["out/value"]}],
    }
    calls = []

    def execute(name, command):
        calls.append(name)
        if kind == "parent_symlink":
            (root / "out").symlink_to(root / "real", target_is_directory=True)
        else:
            (root / "out").mkdir()
            if kind == "leaf_symlink":
                (root / "out/value").symlink_to(root / "real/value")
            else:
                (root / "out/value").write_bytes(b"content")
        return 0

    try:
        observations[kind] = {"report": run(spec, root, execute), "calls": calls}
    except Exception as error:
        observations[kind] = {
            "error": type(error).__name__,
            "detail": str(error),
            "calls": calls,
        }
    if kind == "parent_symlink" and (root / "out").is_symlink():
        (root / "out").unlink()
    if kind == "leaf_symlink" and (root / "out/value").is_symlink():
        (root / "out/value").unlink()
print(json.dumps(observations))
"""


def check(gate):
    probe = gate.case(
        "post-command-output-components",
        {"probe/driver.py": DRIVER},
        "python -I -S probe/driver.py",
    )
    try:
        observed = gate.json(probe)
    except (ValueError, TypeError):
        observed = None
    transport_ok = (
        probe.result.get("ok") is True
        and probe.result.get("returncode") == 0
        and probe.result.get("stopped_by") is None
        and probe.result.get("stderr") == ""
        and isinstance(observed, dict)
    )
    for kind in ("ordinary", "parent_symlink", "leaf_symlink"):
        case = observed.get(kind) if isinstance(observed, dict) else None
        report = case.get("report") if isinstance(case, dict) else None
        wanted = "succeeded" if kind == "ordinary" else "failed"
        valid = (
            transport_ok
            and isinstance(report, dict)
            and case.get("calls") == ["build"]
            and set(report) == {"order", "statuses", "errors", "state"}
            and report.get("order") == ["build"]
            and report.get("statuses") == {"build": wanted}
        )
        if valid and kind != "ordinary":
            errors = report.get("errors")
            valid = (
                isinstance(errors, dict)
                and set(errors) == {"build"}
                and isinstance(errors["build"], str)
                and bool(errors["build"].strip())
                and report.get("state") == {"version": 2, "completed": {}}
            )
        elif valid:
            valid = report.get("errors") == {}
        gate.record(
            "post-command-output-" + kind,
            valid,
            {"observed": case, "transport": probe.result},
        )
