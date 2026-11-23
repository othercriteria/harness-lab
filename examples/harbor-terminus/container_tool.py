"""Container-only Worker filesystem and command operations. Invoked by the outer runner."""

import ctypes
import json
import os
import resource
import signal
import sys
import time
from pathlib import Path

TOOL_DIR = "/opt/harness-worker"
UID = 10001
sys.path.insert(0, TOOL_DIR)


def quiesce(process):
    # As a child subreaper we adopt orphaned descendants, including background jobs
    # that created their own process groups. Only signal our own children.
    end = time.monotonic() + 3
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    reaped = 0
    while time.monotonic() < end:
        process.poll()  # Preserve the direct shell's exit status.
        for pid in map(int, children.read_text().split()):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is not None:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                reaped += int(pid > 0)
            except ChildProcessError:
                return {"verified": True, "reaped_descendants": reaped}
        time.sleep(0.01)
    raise RuntimeError("Worker processes did not quiesce")


def main():
    import read_file
    import run_checks
    import sandbox_worker

    request = json.load(sys.stdin)
    mode = request["mode"]
    args = request["args"]
    if mode == "execute":
        # Only the outer supervisor retains its UID. The model shell and descendants
        # have no privilege transitions, a process limit, and a per-file size limit.
        if (
            Path(__file__).resolve().parent != Path(TOOL_DIR)
            or not Path("/.dockerenv").exists()
        ):
            raise RuntimeError(
                "This helper runs only in the prepared disposable container"
            )
        PR_SET_CHILD_SUBREAPER = 36
        if ctypes.CDLL(None).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise RuntimeError("Cannot supervise task descendants")
        resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
        argv = [
            "setpriv",
            "--reuid",
            str(UID),
            "--regid",
            str(UID),
            "--clear-groups",
            "--no-new-privs",
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            args["command"],
        ]
        return sandbox_worker.run_command(argv, request["timeout"], cleanup=quiesce)
    # Workspace operations use the same permissions as the shell.
    os.setgroups([])
    os.setgid(UID)
    os.setuid(UID)
    root = Path.cwd()
    if mode == "snapshot":
        return run_checks.snapshot(root, args["cwd"])
    if mode == "identity":
        return run_checks.identity(root, args["cwd"])
    if mode == "read_file":
        return read_file.read(root, args)
    if mode not in {"edit_file", "write_file"}:
        raise ValueError("Unsupported operation")
    if args["path"].startswith("/workspace/"):
        args["path"] = args["path"].removeprefix("/workspace/")
    sandbox_worker.WORKSPACE = root
    try:
        outcome = getattr(sandbox_worker, mode)(args)
        return {"returncode": 0, "stdout": json.dumps(outcome), "stderr": ""}
    except sandbox_worker.EditError as error:
        return {"returncode": 1, "stderr": json.dumps(error.details), "stdout": ""}


if __name__ == "__main__":
    print(json.dumps(main()))
