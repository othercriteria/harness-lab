"""Prepare offline task overlays from a clean Terminal-Bench 2.1 checkout."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REVISION = "12b7565679ce5006230b820666353673a133db93"
PYTHON_IMAGE = "python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72"
TASKS = {
    "raman-fitting": (
        "20251031",
        "401fa95d5d491f44a473eda9d2c52930f9565cc889c796eabcb6e20fec26852e",
        ["/app/results.json"],
    ),
    "prove-plus-comm": (
        "20251031",
        "e26741d01681a9da1beeff8b7b7b65fe2b921b8b122a306a3707a81ebd051f73",
        ["/workspace/plus_comm.v", "/workspace/plus_comm.vo"],
    ),
    "polyglot-c-py": (
        "20251031",
        "0f1c3b7816d70cf5551573fd6aeef76893f2ae3000be2419997b6871b5d987ed",
        ["/app/polyglot"],
    ),
    "fix-git": (
        "20260403",
        "389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74",
        ["/app/personal-site"],
    ),
    "log-summary-date-ranges": (
        "20251031",
        "cbeb6ba905c2fec294f16cd5e16e3ea7f2e04d38ac2484d51a11de262aa7dc51",
        ["/app/summary.csv"],
    ),
    "cancel-async-tasks": (
        "20251031",
        "84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d",
        ["/app/run.py"],
    ),
}


ORIGINAL = ("polyglot-c-py", "fix-git")
FOLLOWUP = ("log-summary-date-ranges", "cancel-async-tasks")
WORKDIR = {
    **dict.fromkeys(TASKS, "/app"),
    "fix-git": "/app/personal-site",
    "prove-plus-comm": "/workspace",
}
CONTROL_FILE = {
    "polyglot-c-py": "polyglot/harbor-control.txt",
    "fix-git": "harbor-control.txt",
    "prove-plus-comm": "plus_comm.vo",
    "raman-fitting": "results.json",
    **{task: Path(TASKS[task][2][0]).name for task in FOLLOWUP},
}


def prepare(root, tasks=ORIGINAL):
    checkout = root / "upstream"

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", checkout, *args], text=True
        ).strip()

    if git("rev-parse", "HEAD") != REVISION or git("status", "--porcelain"):
        raise ValueError("Use a clean checkout of the pinned task revision")
    for task in tasks:
        prepare_task(root, task, checkout / "tasks" / task)


def prepare_task(root, task, source):
    tag, digest, artifacts = TASKS[task]
    dest = root / "prepared" / task
    shutil.copytree(source, dest)
    build = root / "build" / task
    shutil.copytree(source / "tests", build / "tests")
    base = f"alexgshaw/{task}@sha256:{digest}"
    # The upstream reference installs these at runtime. Make the same wheels
    # available to both scored agents and the reference before network isolation.
    agent_dependencies = (
        "RUN python -m pip install --no-cache-dir numpy==2.3.1 scipy==1.16.0\n"
        if task == "raman-fitting"
        else ""
    )
    (build / "Dockerfile").write_text(
        f"FROM {base} AS agent\n"
        "RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tmux asciinema && rm -rf /var/lib/apt/lists/*\n"
        f"{agent_dependencies}"
        f"FROM {PYTHON_IMAGE} AS deps\n"
        "RUN python -m pip install --no-cache-dir pytest==8.4.1 pytest-json-ctrf==0.3.5\n"
        f"FROM {base} AS verifier\nCOPY --from=deps /usr/local /usr/local\n"
        "RUN ldconfig\nCOPY tests /tests\n"
    )
    # Keep test_outputs.py byte-identical. Move installation out of timed,
    # offline verification and retain the upstream pytest arguments and reward.
    setup = "cp /tests/test.py /app/test.py\n" if task == "cancel-async-tasks" else ""
    if task == "log-summary-date-ranges":
        # The oracle needs grep and coreutils, already available offline.
        oracle = dest / "solution/solve.sh"
        install = "apt-get update && apt-get install -y grep coreutils"
        assert oracle.read_text().count(install) == 1
        oracle.write_text(
            oracle.read_text().replace(install, "command -v grep date find >/dev/null")
        )
    (build / "tests/test.sh").write_text(
        f"#!/bin/bash\n{setup}if /usr/local/bin/python3.13 -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi\n"
    )
    images = {}
    for role in ("agent", "verifier"):
        image = f"harness078/{task}-{role}:1"
        subprocess.run(
            ["docker", "build", "--target", role, "-t", image, build], check=True
        )
        images[role] = subprocess.check_output(
            ["docker", "image", "inspect", "-f", "{{.Id}}", image], text=True
        ).strip()
    (build / "images.json").write_text(json.dumps(images, indent=2) + "\n")
    config = (source / "task.toml").read_text()
    config = config.replace("artifacts = []", f"artifacts = {json.dumps(artifacts)}")
    config = config.replace("allow_internet = true", "allow_internet = false")
    config = config.replace(f"alexgshaw/{task}:{tag}", f"harness078/{task}-agent:1")
    config += f'\n[verifier.environment]\ndocker_image = "harness078/{task}-verifier:1"\nallow_internet = false\n'
    (dest / "task.toml").write_text(config)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve(), sys.argv[2:] or ORIGINAL)
