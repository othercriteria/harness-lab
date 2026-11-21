"""Replay the sealed two-branch backport through the isolated Git verifier."""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from behavioral_grade import require_cleanup  # noqa: E402
from control import cancellation  # noqa: E402
from git_task import prepare  # noqa: E402
from sandbox import Runtime, perform_tool  # noqa: E402
from verify_git import verify  # noqa: E402

TASK = ROOT / "tasks/git-config-backport-dual-public-tests"
RESTORE = """set -eu
cd /workspace/repo
git switch --detach
git fetch --no-tags /workspace/reference.bundle \
    refs/heads/release/stable:refs/heads/release/stable \
    refs/heads/release/legacy:refs/heads/release/legacy
rm /workspace/reference.bundle
export PYTHONDONTWRITEBYTECODE=1
for branch in release/stable release/legacy; do
    git switch "$branch"
    git rev-parse HEAD
    python -m unittest discover -s tests
done
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for replay receipts")
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runtime = Runtime()
    workspace = output / "workspaces/0000"
    shutil.copytree(TASK / "public", workspace)
    with cancellation():
        workspace = prepare(runtime, workspace, TASK, output)
        shutil.copyfile(
            TASK / "private/reference.bundle", workspace / "reference.bundle"
        )
        shutil.copyfile(
            TASK / "private/reference-handoff.json", workspace / "handoff.json"
        )
        prefix = output / "restore-reference"
        try:
            restored, workspace = perform_tool(
                runtime, workspace, "execute", {"command": RESTORE}, 30, prefix
            )
        finally:
            require_cleanup(prefix, "restore reference")
        if not restored["ok"]:
            raise SystemExit(
                f"Reference setup or public tests failed. See {prefix}.result.json"
            )
        report = verify(runtime, workspace, TASK, output, 60)
    if not (
        report["passed"]
        and report["behavioral"]["passed"]
        and report["delivery"]["passed"]
    ):
        raise SystemExit(f"Reference failed. See {output / 'git-verification'}")
    print(
        f"Both reference tips passed public, canonical, behavioral and delivery checks. Receipts in {output}"
    )


if __name__ == "__main__":
    main()
