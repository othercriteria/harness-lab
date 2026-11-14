"""Offline Git task preparation; repository commands execute only in isolation."""

import json
import shlex
import time

from behavioral_grade import require_cleanup
from sandbox import perform_tool, write_json


def specification(task):
    meta = json.loads((task / "task.json").read_text())
    spec = meta.get("git_repository")
    if meta.get("kind") != "git-backport" or not isinstance(spec, dict):
        raise ValueError("Not an admitted Git task format")
    if spec["bundle"] != "repository.bundle" or spec["directory"] != "repo":
        raise ValueError("Unsupported Git fixture paths")
    if type(spec.get("require_added_tests", True)) is not bool:
        raise ValueError("Invalid regression-test deliverable policy")
    if spec["initial_branch"] not in spec["branches"]:
        raise ValueError("Initial branch is not a target")
    return spec


def prepare(runtime, workspace, task, output, timeout=10):
    spec = specification(task)
    started = time.monotonic()
    prefix = output / "git-prepare"
    command = (
        "git -c init.templateDir= clone --no-hardlinks --origin fixture "
        "--branch "
        + shlex.quote(spec["initial_branch"])
        + " /workspace/repository.bundle /workspace/repo && "
        "git -C /workspace/repo remote remove fixture && "
        "git -C /workspace/repo config core.hooksPath /dev/null && "
        "git -C /workspace/repo config gc.auto 0"
    )
    # Clone retains only the selected local branch. Create all declared refs.
    for name in ["main", *spec["branches"]]:
        if name != spec["initial_branch"]:
            oid = spec["main"] if name == "main" else spec["branches"][name]
            command += (
                " && git -C /workspace/repo branch "
                + shlex.quote(name)
                + " "
                + shlex.quote(oid)
            )
    try:
        result, updated = perform_tool(
            runtime, workspace, "execute", {"command": command}, timeout, prefix
        )
    finally:
        require_cleanup(prefix, "offline Git fixture preparation")
    receipt = {
        "passed": result.get("ok") is True,
        "transport": result,
        "wall_seconds": time.monotonic() - started,
        "workspace": str(updated),
    }
    write_json(output / "git-preparation.json", receipt)
    if not receipt["passed"]:
        raise RuntimeError("Isolated offline Git preparation failed")
    return updated
