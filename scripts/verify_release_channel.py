"""Observe the submitted JS function in isolation and score its returned values outside."""

import json
import shutil

from control import deadline
from delegate_artifacts import tree_files


def verify(runtime, workspace, task, output, remaining):
    cases = json.loads((task / "private/cases.json").read_text())
    if not cases:
        raise ValueError("Release selection requires at least one acceptance case")
    evaluation = output / "evaluation"
    evaluation.mkdir()
    (evaluation / "inputs.json").write_text(
        json.dumps(
            [{"records": case["records"], "channel": case["channel"]} for case in cases]
        )
    )
    shutil.copyfile(task / "private/probe.cjs", evaluation / "probe.cjs")
    # The generic fixture hash omits Python caches and executable modes.
    # Compare the actual exported files for the task's one-file edit contract.
    submitted, modes = tree_files(workspace, with_modes=True)
    original, original_modes = tree_files(task / "public", with_modes=True)
    editable = "current-release.cjs"
    scope_ok = modes == original_modes and all(
        submitted[name] == original[name] for name in original if name != editable
    )
    with deadline(remaining):
        result, _ = runtime.sandbox(
            workspace,
            {
                "mode": "grade",
                "argv": ["/bin/node", "/evaluation/probe.cjs"],
                "timeout": min(10, remaining),
            },
            output / "verification",
            evaluation=(evaluation, "/evaluation"),
        )
    try:
        answers = json.loads(result["stdout"])
    except ValueError:
        answers = None
    complete = isinstance(answers, list) and len(answers) == len(cases)
    checks = {}
    for i, case in enumerate(cases):
        expected = case["expected"]
        typed = ["object" if expected is None else "number", expected]
        checks[case["name"]] = complete and json.dumps(answers[i]) == json.dumps(typed)
    return {
        "passed": result["ok"] and scope_ok and all(checks.values()),
        "allowed_paths_only": scope_ok,
        "checks": checks,
        "transport": result,
    }
