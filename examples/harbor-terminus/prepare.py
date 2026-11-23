"""Prepare two offline task overlays from a clean Terminal-Bench 2.1 checkout."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REVISION = "12b7565679ce5006230b820666353673a133db93"
PYTHON_IMAGE = "python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72"
TASKS = {
    "polyglot-c-py": (
        "20251031",
        "0f1c3b7816d70cf5551573fd6aeef76893f2ae3000be2419997b6871b5d987ed",
        "/app/polyglot",
    ),
    "fix-git": (
        "20260403",
        "389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74",
        "/app/personal-site",
    ),
}


def prepare(root):
    checkout = root / "upstream"

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", checkout, *args], text=True
        ).strip()

    if git("rev-parse", "HEAD") != REVISION or git("status", "--porcelain"):
        raise ValueError("Use a clean checkout of the pinned task revision")
    for task, (tag, digest, artifact) in TASKS.items():
        source = checkout / "tasks" / task
        dest = root / "prepared" / task
        shutil.copytree(source, dest)
        build = root / "build" / task
        shutil.copytree(source / "tests", build / "tests")
        base = f"alexgshaw/{task}@sha256:{digest}"
        (build / "Dockerfile").write_text(
            f"FROM {base} AS agent\n"
            "RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tmux asciinema && rm -rf /var/lib/apt/lists/*\n"
            f"FROM {PYTHON_IMAGE} AS deps\n"
            "RUN python -m pip install --no-cache-dir pytest==8.4.1 pytest-json-ctrf==0.3.5\n"
            f"FROM {base} AS verifier\nCOPY --from=deps /usr/local /usr/local\n"
            "RUN ldconfig\nCOPY tests /tests\n"
        )
        # Keep test_outputs.py byte-identical. Move installation out of timed,
        # offline verification and retain the upstream pytest arguments and reward.
        (build / "tests/test.sh").write_text(
            "#!/bin/bash\nif /usr/local/bin/python3.13 -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi\n"
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
        config = config.replace("artifacts = []", f'artifacts = ["{artifact}"]')
        config = config.replace("allow_internet = true", "allow_internet = false")
        config = config.replace(f"alexgshaw/{task}:{tag}", f"harness078/{task}-agent:1")
        config += f'\n[verifier.environment]\ndocker_image = "harness078/{task}-verifier:1"\nallow_internet = false\n'
        (dest / "task.toml").write_text(config)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
