"""Fetch pinned Harbor packages and rehearse supported offline task overlays."""

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path
from uuid import uuid4

from prepare import REVISION, TASKS, prepare_task

EXAMPLE = Path(__file__).resolve().parent
MANIFEST_SHA256 = "d90b4389992d07ed6f4ab8de963a70241eaa4b60072eeaec4c3b261b6c4a6dd8"


def dataset_pins(root):
    path = root / f"terminal-bench-{REVISION}.toml"
    if path.exists():
        raw = path.read_bytes()
    else:
        url = f"https://raw.githubusercontent.com/harbor-framework/terminal-bench-2-1/{REVISION}/tasks/dataset.toml"
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Terminal-Bench dataset manifest differs from the pin")
    if not path.exists():
        path.write_bytes(raw)
    return {
        task["name"]: task["digest"] for task in tomllib.loads(raw.decode())["tasks"]
    }


async def fetch(root, names):
    from harbor.models.task.id import PackageTaskId
    from harbor.publisher.packager import Packager
    from harbor.tasks.client import TaskClient

    pins = dataset_pins(root) if any("/" not in n for n in names) else {}
    ids = []
    for name in names:
        if "/" in name:
            package, digest = name.split("@")
        else:
            package = f"terminal-bench/{name}"
            if package not in pins:
                raise ValueError(f"No {package} in the pinned Terminal-Bench dataset")
            digest = pins[package]
        org, task = package.split("/")
        ids.append(PackageTaskId(org=org, name=task, ref=digest))
    cache = root / "packages"
    package_paths = [
        cache / pkg.org / pkg.name / pkg.ref.removeprefix("sha256:") for pkg in ids
    ]
    missing = [
        pkg for pkg, path in zip(ids, package_paths, strict=True) if not path.exists()
    ]
    if missing:
        await TaskClient().download_tasks(missing, output_dir=cache)
    paths = {}
    for name, pkg, path in zip(names, ids, package_paths, strict=True):
        for entry in path.rglob("*"):
            if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
                raise ValueError(f"Unexpected package entry: {entry}")
        digest, files = Packager.compute_content_hash(path)
        if f"sha256:{digest}" != pkg.ref or set(files) != {
            p for p in path.rglob("*") if p.is_file()
        }:
            raise ValueError(
                f"Package contents differ from {pkg.org}/{pkg.name}@{pkg.ref}: {path}"
            )
        print(f"{pkg.org}/{pkg.name}@{pkg.ref} → {path}", flush=True)
        paths[name] = path
    return paths


def controls(root, tasks, env):
    label = uuid4().hex[:10]
    for task in tasks:
        for agent in ("oracle", "nop", "worker-control"):
            name = f"hx-{task}-{agent}-{label}"
            print(f"{task} / {agent} → {root / 'trials' / name}", flush=True)
            subprocess.run(
                [
                    root / ".venv/bin/python",
                    EXAMPLE / "trial.py",
                    task,
                    agent,
                    name,
                    "--prepared-images",
                    "--task-timeout",
                ],
                env=env,
                check=True,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Experiment directory on bulk storage")
    parser.add_argument(
        "tasks",
        nargs="+",
        help="Terminal-Bench task names, or org/name@sha256:… for fetch-only",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--fetch-only",
        action="store_true",
        help="Download and verify public inputs for inspection, without building images or running controls",
    )
    modes.add_argument(
        "--controls-only",
        action="store_true",
        help="Repeat CPU controls in an already prepared experiment",
    )
    args = parser.parse_args()
    tasks = list(dict.fromkeys(args.tasks))
    simple = r"[a-z0-9][a-z0-9.-]*"
    if not all(
        re.fullmatch(simple, t)
        or re.fullmatch(rf"{simple}/{simple}@sha256:[a-f0-9]{{64}}", t)
        for t in tasks
    ):
        parser.error("Expected a task name or a digest-pinned Harbor package")
    if not args.fetch_only and set(tasks).difference(TASKS):
        parser.error(
            "Supported overlays: "
            + ", ".join(sorted(TASKS))
            + ". Use --fetch-only to inspect other tasks."
        )
    root = args.root.resolve()
    home = root / "controller-home"
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "HARBOR_SMOKE_ROOT": str(root),
        "HARBOR_TELEMETRY": "0",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    if args.controls_only:
        controls(root, tasks, env)
        return
    if not args.fetch_only:
        for task in tasks:
            if any(
                (root / directory / task).exists()
                for directory in ("prepared", "build")
            ):
                parser.error(
                    f"Preparation exists for {task}. Use --controls-only for a completed preparation or choose a fresh root."
                )
    venv = root / ".venv"
    if Path(sys.prefix).resolve() != venv.resolve():
        if venv.is_symlink():
            parser.error(
                "Choose a root with its own Harbor environment for installation"
            )
        if not venv.exists():
            subprocess.run(["uv", "venv", "--python", "3.13", venv], check=True)
        python = venv / "bin/python"
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                python,
                "-r",
                EXAMPLE / "requirements.txt",
            ],
            check=True,
        )
        os.execve(
            python,
            [str(python), "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
            env,
        )
    paths = asyncio.run(fetch(root, tasks))
    if not args.fetch_only:
        for task, source in paths.items():
            prepare_task(root, task, source)
        controls(root, tasks, env)


if __name__ == "__main__":
    main()
