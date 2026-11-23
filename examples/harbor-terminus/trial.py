"""One trial on the pinned Harbor release, with host log mounts disabled for the agent."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from harbor.models.trial.config import TrialConfig
from harbor.trial.hooks import TrialEvent
from harbor.trial.trial import Trial

MODEL = "qwen38-27b-ranalayout-q4"


def warm(origin, instruction):
    template = (
        files("harbor.agents.terminus_2")
        .joinpath("templates/terminus-json-plain.txt")
        .read_text()
    )
    prompt = template.format(
        instruction=instruction.read_text().strip(), terminal_state=""
    )
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1,
        "seed": 19550,
        "temperature": 0.6,
        "cache_prompt": True,
        "reasoning_budget_tokens": 2048,
    }
    request = urllib.request.Request(
        origin + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    return {
        "wall_seconds": time.monotonic() - started,
        "usage": result["usage"],
        "timings": result.get("timings"),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    }


async def main():
    root = Path(os.environ["HARBOR_SMOKE_ROOT"]).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("polyglot-c-py", "fix-git"))
    parser.add_argument("agent", choices=("terminus-2", "nop", "oracle"))
    parser.add_argument("name", help="Fresh trial name")
    parser.add_argument(
        "origin", nargs="?", help="Owned loopback endpoint for Terminus"
    )
    args = parser.parse_args()
    task, agent, name = args.task, args.agent, args.name
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        parser.error("Use a lowercase alphanumeric trial name with optional hyphens")
    directory = root / "trials" / name
    if directory.exists():
        raise FileExistsError(directory)
    agent_config = {"name": agent, "override_timeout_sec": 600}
    if agent == "terminus-2":
        if args.origin is None:
            parser.error("Terminus-2 requires a local endpoint")
        origin = args.origin
        addr = urlparse(origin)
        if (
            addr.scheme != "http"
            or addr.hostname != "127.0.0.1"
            or not addr.port
            or origin != f"http://127.0.0.1:{addr.port}"
        ):
            raise ValueError("Pass the owned loopback HTTP origin")
        warmup = warm(origin, root / "prepared" / task / "instruction.md")
        agent_config.update(
            exclude_logs=["*"],
            model_name="openai/" + MODEL,
            kwargs={
                "api_base": origin + "/v1",
                "temperature": 0.6,
                "record_terminal_session": False,
                "model_info": {
                    "max_tokens": 32768,
                    "max_input_tokens": 32768,
                    "max_output_tokens": 8192,
                    "input_cost_per_token": 0,
                    "output_cost_per_token": 0,
                    "litellm_provider": "openai",
                    "mode": "chat",
                },
                "llm_call_kwargs": {
                    "seed": 19550,
                    "extra_body": {
                        "reasoning_budget_tokens": 2048,
                        "reasoning_budget_message": "",
                    },
                },
            },
        )
    config = TrialConfig.model_validate(
        {
            "task": {"path": str(root / "prepared" / task)},
            "environment": {"type": "docker", "kwargs": {"auto_mounting": False}},
            "agent": agent_config,
            "trial_name": name,
            "trials_dir": str(root / "trials"),
        }
    )
    trial = await Trial.create(config)

    if agent == "terminus-2":
        (directory / "warmup.json").write_text(json.dumps(warmup, indent=2) + "\n")

    async def prepare_agent(event):
        env = trial.agent_environment
        check = await env.exec(
            command="test ! -e /tests && test ! -e /var/run/docker.sock && mkdir -p /logs/agent /logs/artifacts"
        )
        # Inspect the effective main service, independently of the task configuration.
        cid = subprocess.check_output(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + env.session_id,
                "--filter",
                "label=com.docker.compose.service=main",
            ],
            text=True,
        ).strip()
        info = json.loads(subprocess.check_output(["docker", "inspect", cid]))[0]
        boundary = {
            "network_mode": info["HostConfig"]["NetworkMode"],
            "mounts": info["Mounts"],
            "privileged": info["HostConfig"]["Privileged"],
            "memory": info["HostConfig"]["Memory"],
            "image": info["Image"],
        }
        if boundary["network_mode"].startswith("container:"):
            sidecar = json.loads(
                subprocess.check_output(
                    ["docker", "inspect", boundary["network_mode"].split(":", 1)[1]]
                )
            )[0]
            policy = [
                v
                for v in sidecar["Config"]["Env"]
                if v.startswith("EGRESS_CONTROL_INITIAL_NETWORK_MODE=")
            ]
            boundary["initial_egress_policy"] = policy
            if policy != ["EGRESS_CONTROL_INITIAL_NETWORK_MODE=no-network"]:
                raise RuntimeError("Task sidecar did not start offline")
        elif boundary["network_mode"] != "none":
            raise RuntimeError("Unexpected task network mode")
        (directory / "agent-boundary.json").write_text(
            json.dumps(boundary, indent=2) + "\n"
        )
        if boundary["mounts"] or boundary["privileged"]:
            raise RuntimeError("Unexpected task container boundary")
        if (
            agent == "terminus-2"
            and (await env.exec(command="test ! -e /solution")).return_code
        ):
            raise RuntimeError("Reference content visible to model")
        if check.return_code:
            raise RuntimeError("Agent setup or isolation check failed")

    trial.add_hook(TrialEvent.AGENT_START, prepare_agent)
    result = await trial.run()
    print(
        result.verifier_result,
        result.exception_info and result.exception_info.exception_type,
        flush=True,
    )
    if result.verifier_result is None:
        raise SystemExit(2)
    if agent in ("oracle", "nop") and (
        result.exception_info
        or result.verifier_result.rewards != {"reward": int(agent == "oracle")}
    ):
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
