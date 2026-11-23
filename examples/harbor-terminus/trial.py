"""One trial on the pinned Harbor release, with host log mounts disabled for the agent."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import time
import tomllib
import urllib.request
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from harbor.models.trial.config import TrialConfig
from harbor.trial.hooks import TrialEvent
from harbor.trial.trial import Trial
from prepare import FOLLOWUP, TASKS

MODEL = "qwen38-27b-ranalayout-q4"
SMOKE_SECONDS = 600


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
    parser.add_argument("task", choices=TASKS)
    parser.add_argument(
        "agent", choices=("terminus-2", "nop", "oracle", "worker", "worker-control")
    )
    parser.add_argument("name", help="Fresh trial name")
    parser.add_argument(
        "origin", nargs="?", help="Owned loopback endpoint for the model"
    )
    parser.add_argument(
        "--prepared-images",
        action="store_true",
        help="Use the image IDs from this machine's prepare.py run for a separate smoke",
    )
    parser.add_argument(
        "--task-timeout",
        action="store_true",
        help="Use the task's declared Harbor agent timeout (smoke default: 600 seconds).",
    )
    args = parser.parse_args()
    task, agent, name = args.task, args.agent, args.name
    prepared_images = args.prepared_images or task in FOLLOWUP
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        parser.error("Use a lowercase alphanumeric trial name with optional hyphens")
    directory = root / "trials" / name
    if directory.exists():
        raise FileExistsError(directory)
    agent_config = {"name": agent}
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
    worker_agent = agent in ("worker", "worker-control")
    if worker_agent:
        origin = args.origin or (
            "http://127.0.0.1:1" if agent == "worker-control" else None
        )
        if origin is None or not re.fullmatch(r"http://127[.]0[.]0[.]1:[0-9]+", origin):
            parser.error("Worker requires an owned loopback endpoint")
    example = Path(__file__).resolve().parent
    if worker_agent or prepared_images or args.task_timeout:
        if prepared_images:
            pins = json.loads((root / "build" / task / "images.json").read_bytes())
            options = ["--format", "{{.Id}}"]
            binding = "local preparation image IDs"
        else:
            baseline = example.parents[1] / "results/harbor-terminus-smoke-078.json"
            manifests = json.loads(baseline.read_bytes())["paired_images"][
                "linux_amd64_manifests"
            ]
            pins = {role: manifests[f"{task}-{role}"] for role in ("agent", "verifier")}
            options = [
                "--platform",
                "linux/amd64",
                "--format",
                "{{.Descriptor.Digest}}",
            ]
            binding = "baseline Linux/amd64 platform manifests"
        for role in ("agent", "verifier"):
            image = f"harness078/{task}-{role}:1"
            actual = subprocess.check_output(
                ["docker", "image", "inspect", image, *options], text=True
            ).strip()
            if actual != pins[role]:
                raise ValueError(f"{image} differs from {binding}")
    if worker_agent:
        budget = SMOKE_SECONDS
        if args.task_timeout:
            with (root / "prepared" / task / "task.toml").open("rb") as file:
                budget = tomllib.load(file).get("agent", {}).get("timeout_sec")
            if budget is None or not math.isfinite(budget) or budget <= 0:
                parser.error("Worker requires a finite positive task ceiling")
        agent_config = {
            "import_path": "harbor_worker:Worker",
            "model_name": MODEL,
            "exclude_logs": ["*"],
            "kwargs": {
                "task_key": task,
                "budget_seconds": budget,
                "endpoint": origin,
                "control": agent == "worker-control",
            },
        }
    if not args.task_timeout:
        agent_config["override_timeout_sec"] = SMOKE_SECONDS
    config = TrialConfig.model_validate(
        {
            "task": {"path": str(root / "prepared" / task)},
            "environment": {"type": "docker", "kwargs": {"auto_mounting": False}},
            "agent": agent_config,
            **(
                {
                    "verifier": {
                        "import_path": "harbor_worker:ControlVerifier",
                        "kwargs": {"skip_tests_upload": True},
                    }
                }
                if agent == "worker-control"
                else {}
            ),
            "trial_name": name,
            "trials_dir": str(root / "trials"),
        }
    )
    trial = await Trial.create(config)

    if worker_agent:
        budget = trial.agent_timeout_sec
        if trial.agent.budget_seconds != budget:
            raise ValueError("Worker and Harbor agent ceilings differ")
        if agent == "worker":
            warm_dir = root / "warm" / name
            warm_dir.parent.mkdir(exist_ok=True)
            subprocess.run(
                [
                    example.parents[1] / ".venv/bin/python",
                    example / "worker_loop.py",
                    "warm",
                    task,
                    origin,
                    "",
                    warm_dir,
                    str(budget),
                ],
                input=(root / "prepared" / task / "instruction.md").read_bytes(),
                check=True,
            )
    if worker_agent or prepared_images or args.task_timeout:
        (directory / "image-binding.json").write_text(
            json.dumps({"source": binding, "images": pins}, indent=2) + "\n"
        )
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
            "docker_limits": {
                key: info["HostConfig"].get(key)
                for key in (
                    "NanoCpus",
                    "CpuQuota",
                    "CpuPeriod",
                    "MemorySwap",
                    "StorageOpt",
                )
            },
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
        if (agent == "terminus-2" or worker_agent) and (
            await env.exec(command="test ! -e /solution")
        ).return_code:
            raise RuntimeError("Reference content visible to model")
        if check.return_code:
            raise RuntimeError("Agent setup or isolation check failed")

    trial.add_hook(TrialEvent.AGENT_START, prepare_agent)
    started = time.monotonic()
    result = await trial.run()
    timing = {
        "run_monotonic_seconds": time.monotonic() - started,
        "agent_limit_seconds": trial.agent_timeout_sec,
        "verifier_limit_seconds": trial.verifier_timeout_sec,
        "agent_setup_limit_seconds": trial.agent_setup_timeout_sec,
        "environment_build_limit_seconds": trial.environment_build_timeout_sec,
    }
    (directory / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    print(
        result.verifier_result,
        result.exception_info and result.exception_info.exception_type,
        flush=True,
    )
    if result.verifier_result is None:
        raise SystemExit(2)
    if agent == "worker-control":
        proof = json.loads((directory / "control-transfer.json").read_text())
        lines = proof["output"].strip().splitlines()
        (record_path,) = (directory / "agent/worker/checks").glob("c*.json")
        record = json.loads(record_path.read_text())
        if record["returncode"] != 0 or record["exception_info"]:
            raise RuntimeError(
                "Control history, process cleanup or marker check failed"
            )
        if task == "fix-git":
            output = record["output"].strip().splitlines()
            if (
                len(lines) != 3
                or lines[0] != "harbor-control"
                or not re.fullmatch("[0-9a-f]{40}", lines[1])
                or lines[1] != output[-1]
            ):
                raise RuntimeError(
                    "Verifier did not observe the submitted branch and commit"
                )
        if (
            proof["returncode"]
            or lines[-1:] != ["after"]
            or result.exception_info
            or result.verifier_result.rewards != {"reward": 0}
        ):
            raise RuntimeError(
                "Scripted control transfer or expected negative reward failed"
            )
    if agent in ("oracle", "nop") and (
        result.exception_info
        or result.verifier_result.rewards != {"reward": int(agent == "oracle")}
    ):
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
