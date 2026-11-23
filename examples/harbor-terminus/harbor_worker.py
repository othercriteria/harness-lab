"""Harbor external agent entry point. Only the selected public helper files enter the container."""

import asyncio
import json
import subprocess
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.verifier.verifier import Verifier
from prepare import CONTROL_FILE, WORKDIR

EXAMPLE = Path(__file__).resolve().parent
LAB = EXAMPLE.parents[1]


class Worker(BaseAgent):
    def __init__(
        self, *args, task_key, endpoint, budget_seconds=600, control=False, **kwargs
    ):
        self.task_key = task_key
        self.endpoint = endpoint
        self.budget_seconds = budget_seconds
        self.control = control
        super().__init__(*args, **kwargs)

    @staticmethod
    def name():
        return "harness-lab-worker"

    def version(self):
        return "1"

    async def setup(self, environment):
        cwd = WORKDIR[self.task_key]
        # The committed upstream fixture uses the image's Git identity. Give the unprivileged
        # task account that same task-local identity, without forwarding the operator's Git config.
        command = f"""set -eu
test ! -e /tests
test ! -e /solution
test "$(pwd -P)" = "{cwd}"
command -v setpriv >/dev/null
mkdir -p /opt/harness-worker /checks /tmp/worker-home
if test "{cwd}" != /workspace; then
    test ! -e /workspace
    test ! -L /workspace
    ln -sT "{cwd}" /workspace
fi
if test -f /root/.gitconfig; then cp /root/.gitconfig /tmp/worker-home/.gitconfig; fi
chown -R 10001:10001 "{cwd}" /tmp/worker-home
"""
        check = await environment.exec(command=command)
        if check.return_code:
            raise RuntimeError("Worker task setup failed: " + str(check.stderr))
        for name in (
            "read_file.py",
            "tool_arguments.py",
            "call_budget.py",
            "run_checks.py",
            "sandbox_worker.py",
            "container_tool.py",
        ):
            src = (
                EXAMPLE / name
                if name == "container_tool.py"
                else LAB / "scripts" / name
            )
            await environment.upload_file(src, "/opt/harness-worker/" + name)

    async def run(self, instruction, environment, context):
        cid = subprocess.check_output(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + environment.session_id,
                "--filter",
                "label=com.docker.compose.service=main",
            ],
            text=True,
        ).strip()
        if not cid or "\n" in cid:
            raise RuntimeError("Expected one task container")
        info = json.loads(subprocess.check_output(["docker", "inspect", cid]))[0]
        if (
            info["HostConfig"]["PidMode"] not in (None, "", "private")
            or info["Mounts"]
            or info["HostConfig"]["Privileged"]
        ):
            raise RuntimeError("Unexpected task container isolation")
        expected = json.loads(
            (self.logs_dir.parent / "agent-boundary.json").read_text()
        )
        if (
            info["Image"] != expected["image"]
            or info["HostConfig"]["NetworkMode"] != expected["network_mode"]
        ):
            raise RuntimeError("Task boundary changed")
        output = self.logs_dir / "worker"
        with (self.logs_dir / "worker.log").open("wb") as log:
            child = await asyncio.create_subprocess_exec(
                str(LAB / ".venv/bin/python"),
                str(EXAMPLE / "worker_loop.py"),
                "control" if self.control else "model",
                self.task_key,
                self.endpoint,
                cid,
                str(output),
                str(self.budget_seconds),
                stdin=asyncio.subprocess.PIPE,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                await child.communicate(instruction.encode())
            finally:
                if child.returncode is None:
                    child.kill()
                    await child.wait()
        if child.returncode:
            raise RuntimeError(
                f"Worker exited {child.returncode}; see agent/worker.log"
            )
        outcome = json.loads((output / "outcome.json").read_text())
        context.metadata = outcome
        context.n_input_tokens = outcome["input_tokens"]
        context.n_output_tokens = outcome["output_tokens"]
        if outcome["exit_status"] not in ("Submitted", "Blocked"):
            raise RuntimeError(
                f"Worker stopped: {outcome.get('reason') or outcome['exit_status']}"
            )


class ControlVerifier(Verifier):
    """Observe the scripted control after the standard artifact transfer, before grading."""

    async def verify(self):
        task = self.task.short_name
        probe = (
            f"cat {WORKDIR[task]}/{CONTROL_FILE[task]}"
            if task != "fix-git"
            else "git -c safe.directory=/app/personal-site branch --show-current && git -c safe.directory=/app/personal-site rev-parse HEAD && git -c safe.directory=/app/personal-site show HEAD:harbor-control.txt"
        )
        result = await self.environment.exec(command=probe)
        (self.trial_paths.trial_dir / "control-transfer.json").write_text(
            json.dumps(
                {"returncode": result.return_code, "output": result.stdout}, indent=2
            )
            + "\n"
        )
        return await super().verify()
