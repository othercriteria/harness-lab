"""Launch one reviewed GPU transaction; restoration owners remain outside caps."""

import argparse
import json
import os
import shutil
from pathlib import Path

from check_fixtures import manifest
from protocol import (
    admit_tasks,
    campaign_timeout,
    load_protocol,
    profiles,
    protocols,
    require_task_protocol,
    server_resources,
    tasks,
)
from sandbox import write_json

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=profiles(), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--tasks",
        nargs="+",
        choices=tasks(),
        default=["config-overlay"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--protocol", choices=protocols(), default="mvp")
    parser.add_argument("--seeds", nargs="+", type=int, default=[42])
    parser.add_argument(
        "--weight-verification", choices=("full", "metadata"), default="full"
    )
    parser.add_argument(
        "--split", choices=["development", "reserved"], default="development"
    )
    args = parser.parse_args()
    admit_tasks(args.tasks, args.split)
    limits = load_protocol(args.protocol)
    for task in args.tasks:
        metadata = json.loads((PROJECT / "tasks" / task / "task.json").read_text())
        require_task_protocol(metadata, limits)
    profile = json.loads((PROJECT / "configs/servers.json").read_text())[args.profile]
    resources = server_resources(profile)
    budget = campaign_timeout(
        limits,
        len(args.tasks) * len(args.seeds),
        resources["setup_allowance_seconds"],
    )
    output = args.output.resolve()
    if not output.is_relative_to("/bulk/dlk/local-harness/runs") or output.exists():
        parser.error("Use a fresh directory under project bulk runs")
    python = str(PROJECT / ".venv/bin/python")
    command = [
        python,
        str(PROJECT / "scripts/serve_trial.py"),
        "--profile",
        args.profile,
        "--output",
        str(output / "experiment"),
        "--tasks",
        *args.tasks,
        "--protocol",
        args.protocol,
        "--split",
        args.split,
        "--weight-verification",
        args.weight_verification,
        "--seeds",
        *map(str, args.seeds),
    ]
    wrappers = [
        (
            "with_memory_scope.py",
            "memory",
            [
                "--memory-max-gib",
                str(resources["memory_max_gib"]),
                "--minimum-available-gib",
                str(resources["minimum_available_gib"]),
                "--command-timeout",
                str(budget),
                "--shutdown-timeout",
                "90",
                "--require-inherited-gpu-lock",
                "--whole-command-global-guard",
            ],
        ),
        ("with_ollama_released.py", "ollama", ["--command-timeout", str(budget + 120)]),
        ("with_speech_released.py", "voice", ["--command-timeout", str(budget + 300)]),
        (
            "with_background_released.py",
            "background",
            ["--command-timeout", str(budget + 600)],
        ),
    ]
    for script, name, flags in wrappers:
        command = [
            python,
            str(PROJECT / "scripts" / script),
            "--output",
            str(output / name),
            *flags,
            "--",
            *command,
        ]
    if args.dry_run:
        print(json.dumps(command, indent=2))
        return
    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    for name in ("scripts", "configs", "tasks"):
        shutil.copytree(
            PROJECT / name, inputs / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    for name in ("uv.lock", "flake.lock", "pyproject.toml"):
        shutil.copyfile(PROJECT / name, inputs / name)
    write_json(output / "inputs.json", manifest(inputs))
    write_json(output / "command.json", command)
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
