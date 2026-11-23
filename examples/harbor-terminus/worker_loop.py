"""Run the Lab Worker on one live, isolated Harbor workspace."""

# The Lab scripts run in their own environment, separate from Harbor.
# ruff: noqa: E402
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent
LAB = EXAMPLE.parents[1]
sys.path.insert(0, str(LAB / "scripts"))

from coding_agent import IsolatedEnvironment, LocalModel
from control import deadline
from fresh_context import FreshContext
from mini_bootstrap import DefaultAgent
from observations import ObservationHistory
from prepare import CONTROL_FILE, WORKDIR
from resumption_digest import from_snapshots
from run_trial import configure_agent
from sandbox import write_json

MODEL = "qwen38-27b-ranalayout-q4"


class ContainerEnvironment(IsolatedEnvironment):
    def __init__(self, cid, output, limits):
        super().__init__(
            None,
            None,
            output,
            limits["tool_timeout_seconds"],
            limits["tool_call_limit"],
            max_command_bytes=limits["max_command_bytes"],
            structured_finalization=True,
            read_file=True,
            exact_text_edit=True,
            whole_file_write=True,
            run_checks=True,
        )
        self.cid = cid
        self.published_history = None
        self.published_checks = set()
        self.initial_snapshot = self.remote("snapshot", {"cwd": "."}) if cid else {}

    def remote(self, mode, args):
        completed = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "HOME=/tmp/worker-home",
                "-e",
                "GIT_TERMINAL_PROMPT=0",
                self.cid,
                "python3",
                "-I",
                "-S",
                "/opt/harness-worker/container_tool.py",
            ],
            input=json.dumps(
                {"mode": mode, "args": args, "timeout": self.timeout}
            ).encode(),
            capture_output=True,
            timeout=self.timeout + 10,
            check=True,
        )
        return json.loads(completed.stdout)

    def check_identity(self, cwd):
        return self.remote("identity", {"cwd": cwd})

    def public_state(self, history):
        return from_snapshots(
            self.initial_snapshot,
            self.remote("snapshot", {"cwd": "."}),
            history,
            self.check_identity,
        )

    def read_workspace(self, arguments):
        return self.remote("read_file", arguments)

    def workspace_tool(self, mode, arguments, prefix, **options):
        if (
            self.history_archive is not None
            and self.history_archive != self.published_history
        ):
            subprocess.run(
                ["docker", "exec", self.cid, "rm", "-rf", "/history"], check=True
            )
            subprocess.run(
                ["docker", "cp", str(self.history_archive), self.cid + ":/history"],
                check=True,
            )
            self.published_history = self.history_archive
        for path in sorted(self.checks.glob("c*.json")):
            if path.name not in self.published_checks:
                subprocess.run(
                    ["docker", "cp", str(path), self.cid + ":/checks/" + path.name],
                    check=True,
                )
                self.published_checks.add(path.name)
        write_json(
            prefix.with_suffix(".request.json"),
            {
                "mode": mode,
                "arguments": arguments,
                "interface": options.get("public_interface"),
            },
        )
        result = self.remote(mode, arguments)
        write_json(prefix.with_suffix(".result.json"), result)
        # Docker exec has returned. Shells can spawn children, so require the
        # trusted supervisor's separate evidence that it also reaped descendants.
        if mode == "execute":
            cleanup = result["quiescence"]
            if cleanup.get("verified") is not True:
                raise RuntimeError("Unverified Harbor shell cleanup")
        elif mode in ("write_file", "edit_file"):
            cleanup = {"verified": True, "boundary": "synchronous file helper exited"}
        else:
            raise ValueError("Unsupported workspace operation")
        write_json(prefix.with_suffix(".cleanup.json"), cleanup)
        return result

    def serialize(self):
        return {
            "info": {
                "environment": {
                    "kind": "harbor-docker",
                    "calls": self.calls,
                    "workspace": "/workspace",
                }
            }
        }


class Warmed(Exception):
    pass


class WarmModel(LocalModel):
    def count_tokens(self, payload, phase):
        request = {**payload, "max_tokens": 1}
        started = time.monotonic()
        req = urllib.request.Request(
            self.origin + "/v1/chat/completions",
            data=json.dumps(request).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(req, timeout=90) as response:
            result = json.load(response)
        write_json(
            self.output / "warmup.json",
            {
                "usage": result["usage"],
                "seconds": time.monotonic() - started,
                "messages_sha256": hashlib.sha256(
                    json.dumps(request["messages"]).encode()
                ).hexdigest(),
                "tools": [x["function"]["name"] for x in request["tools"]],
            },
        )
        raise Warmed


def control_actions(task):
    target = CONTROL_FILE[task]
    setup = {
        "polyglot-c-py": "mkdir -p polyglot",
        "fix-git": "git switch -c harbor-control",
    }.get(task, "true")
    actions = [
        (
            "bash",
            {
                "command": setup
                + " && { sleep 60 </dev/null >/dev/null 2>&1 & echo $! > /tmp/control-pid; }"
            },
        ),
        ("write_file", {"path": target, "content": "before\n"}),
        ("read_file", {"path": target}),
        ("edit_file", {"path": target, "old_text": "before", "new_text": "after"}),
        (
            "run_checks",
            {
                "cwd": ".",
                "command": f'test -r /history/manifest.json && test ! -w /history/manifest.json && test ! -e "/proc/$(cat /tmp/control-pid)" && test "$(cat {target})" = after'
                + (
                    " && git add harbor-control.txt && git commit -qm harbor-control && git rev-parse HEAD"
                    if task == "fix-git"
                    else ""
                ),
            },
        ),
        (
            "finish_attempt",
            {
                "disposition": "submitted",
                "summary": "Edited and checked the control marker.",
                "blocker": None,
                "unverified": [],
                "evidence": [
                    {
                        "kind": "observation",
                        "observation_id": "o0005",
                        "supports": "Marker check completed.",
                    }
                ],
            },
        ),
    ]
    return actions


class ControlModel(LocalModel):
    def query(self, messages):
        from finish_attempt import actions as parse_actions

        # Inject context pressure only in the scripted rehearsal. Verify that
        # real cleanup receipts permit recovery and the next shell can read history.
        if self.calls == 4:
            recovered = self.fresh_context.consider_pressure(
                messages,
                self,
                {"input_tokens_after": 32767, "available_completion_tokens": 1},
            )
            if not recovered:
                raise RuntimeError("Control could not recover its context")
        name, args = self.actions[self.calls]
        self.calls += 1
        tool = {
            "id": f"cpu-{self.calls}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
        message = {"role": "assistant", "content": "", "tool_calls": [tool]}
        message["extra"] = {
            "actions": parse_actions(
                message,
                {},
                self.history,
                finish_reason="tool_calls",
                edit_file_enabled=True,
                write_file_enabled=True,
                read_file_enabled=True,
                run_checks_enabled=True,
            )
        }
        return message


def main():
    mode, task, origin, cid, out = sys.argv[1:]
    output = Path(out)
    output.mkdir(exist_ok=False)
    limits = json.loads(
        (LAB / "configs/recipe-inputs/166f69c7c3ef2da7-protocol.json").read_text()
    )
    limits.update(
        seed=19550,
        agent_wall_seconds=600,
        task_wall_seconds=600,
        verification_reserve_seconds=0,
        request_timeout_seconds=600,
    )
    # Upstream task instructions are the public input. Workspace files live in
    # the task image; there is no Lab starter-file preload.
    limits["initial_repository"] = None
    config = configure_agent(
        json.loads((LAB / "configs/agent.json").read_text()),
        limits,
        "delegated-v1",
        harbor_workspace=WORKDIR[task],
    )
    task_text = sys.stdin.read()
    write_json(
        output / "effective-config.json",
        {"limits": limits, "agent": config, "task": task_text},
    )
    env = ContainerEnvironment(cid, output, limits)
    cls = {"warm": WarmModel, "control": ControlModel, "model": LocalModel}[mode]
    model = cls(origin, MODEL, {"temperature": 0.6}, limits, output)
    model.tool_environment = env
    model.history = env.history = ObservationHistory(
        output,
        limits["context_policy"],
        expose_ids=True,
        call_limit=limits["tool_call_limit"],
    )
    model.fresh_context = env.fresh_context = FreshContext(
        output, limits["fresh_context"], env, model=model
    )
    if mode == "control":
        model.actions = control_actions(task)
    agent = DefaultAgent(model, env, **config, output_path=output / "trajectory.json")
    env.agent_deadline = model.agent_deadline = time.monotonic() + 600
    model.fresh_context.start(env.agent_deadline, 600)
    try:
        with deadline(600):
            outcome = agent.run(task_text)
    except Warmed:
        if mode == "warm":
            return
        raise
    write_json(
        output / "outcome.json",
        {
            "exit_status": outcome.get("exit_status"),
            "calls": model.calls,
            "tool_calls": env.calls,
            "input_tokens": model.prompt_tokens,
            "output_tokens": model.completion_tokens,
            "fresh_context_resets": model.fresh_context.reset_count,
        },
    )
    if mode == "control" and outcome.get("exit_status") != "Submitted":
        raise RuntimeError("Control failed")


if __name__ == "__main__":
    main()
