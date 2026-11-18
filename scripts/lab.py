"""Local Harness Lab project conveniences. Only pilot launches inference and changes GPU services."""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from protocol import profiles, protocols, tasks

PROJECT = Path(__file__).resolve().parents[1]


def command(argv, timeout=15):
    try:
        result = subprocess.run(
            argv,
            cwd=PROJECT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": argv,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"argv": argv, "error": str(error)}


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.load(response)
        if "pypi.org" in url:
            data = {"version": data["info"]["version"]}
        return {"url": url, "data": data}
    except (OSError, ValueError, KeyError) as error:
        return {"url": url, "error": str(error)}


def storage():
    root = Path(
        os.environ.get("LOCAL_HARNESS_ROOT", "/bulk/dlk/local-harness")
    ).resolve()
    if not root.is_relative_to("/bulk/dlk") or root == Path("/bulk/dlk"):
        raise ValueError(f"Storage must be beneath /bulk/dlk, got {root}")
    ancestor = root
    while not ancestor.exists():
        ancestor = ancestor.parent
    mount = command(["findmnt", "-n", "-o", "SOURCE", "-T", str(ancestor)])
    return root, ancestor, mount


def prepare_storage():
    root, _, mount = storage()
    if mount.get("returncode") != 0 or mount["stdout"] != "slowdisk/bulk":
        raise RuntimeError("Storage is not verified on slowdisk/bulk; refusing writes")
    for relative in ("runs", "cache/uv"):
        destination = root / relative
        if not destination.resolve().is_relative_to(root):
            raise RuntimeError(f"Storage symlink escapes root: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
    return root


def doctor(probe_write=False):
    root, ancestor, mount = storage()
    jobs = {
        "gpu": lambda: command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader",
            ]
        ),
        "nix_daemon": lambda: command(["nix", "store", "info", "--json"]),
        "services": lambda: command(
            [
                "systemctl",
                "show",
                "ollama-background.target",
                "gpu-voice.target",
                "--property=Id,LoadState,ActiveState,SubState",
                "--no-pager",
            ]
        ),
        "user_services": lambda: command(
            ["systemctl", "--user", "show", "--property=Version"]
        ),
        "ollama": lambda: get_json("http://127.0.0.1:11434/api/ps"),
        "package_network": lambda: get_json(
            "https://pypi.org/pypi/mini-swe-agent/2.4.6/json"
        ),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
        observations = {name: future.result() for name, future in futures.items()}
    write_probe = {"status": "not_requested"}
    if probe_write:
        try:
            if not root.is_dir():
                raise RuntimeError(
                    "Run ./lab setup or the resume helper to create storage"
                )
            if mount.get("stdout") != "slowdisk/bulk":
                raise RuntimeError("Wrong storage mount")
            with tempfile.TemporaryFile(dir=root) as stream:
                stream.write(b"local-harness-access-probe\n")
                stream.flush()
            write_probe = {"status": "passed"}
        except (OSError, RuntimeError) as error:
            write_probe = {"status": "failed", "error": str(error)}
    checks = {
        name: value.get("returncode") == 0
        for name, value in observations.items()
        if "url" not in value
    }
    checks["package_network"] = "data" in observations["package_network"]
    checks["storage_mount"] = (
        mount.get("returncode") == 0 and mount.get("stdout") == "slowdisk/bulk"
    )
    if probe_write:
        checks["bulk_write"] = write_probe["status"] == "passed"
    return {
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "tools": {
            name: shutil.which(name) for name in ("uv", "ruff", "bwrap", "systemd-run")
        },
        "storage": {
            "root": str(root),
            "ancestor": str(ancestor),
            "mount": mount,
            "write_probe": write_probe,
        },
        "observations": observations,
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "No model or service mutations; only --probe-write performs a temporary write",
            "Does not verify service-control authorization or candidate-code containment",
            "Ollama observation is informational; a dedicated llama.cpp server can be used",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    preflight = sub.add_parser("doctor", help="Inspect host access; no service changes")
    preflight.add_argument("--require-access", action="store_true")
    preflight.add_argument(
        "--probe-write",
        action="store_true",
        help="Test a temporary write in existing bulk root",
    )
    preflight.add_argument("--report", type=Path, help="Save a new JSON report")
    sub.add_parser(
        "setup", help="Prepare bulk cache and lock/install Python dependencies"
    )
    sub.add_parser("check", help="Check lint, formatting, and trusted task fixtures")
    pilot = sub.add_parser("pilot", help="Run a guarded, restoring GPU campaign")
    pilot.add_argument("--profile", choices=profiles(), required=True)
    pilot.add_argument("--output", type=Path, required=True)
    pilot.add_argument(
        "--tasks",
        nargs="+",
        choices=tasks(),
        default=["config-overlay"],
    )
    pilot.add_argument("--dry-run", action="store_true")
    pilot.add_argument("--protocol", choices=protocols(), default="mvp")
    pilot.add_argument("--seeds", nargs="+", type=int, default=[42])
    pilot.add_argument(
        "--weight-verification", choices=("full", "metadata"), default="full"
    )
    pilot.add_argument(
        "--split", choices=["development", "reserved"], default="development"
    )
    results = sub.add_parser("results", help="Read preserved campaign summaries")
    results.add_argument("campaigns", nargs="+", type=Path)
    results.add_argument("--report", type=Path)
    observer = sub.add_parser("observe", help="Serve the read-only loopback dashboard")
    observer.add_argument("--port", type=int, default=8765)
    registry = sub.add_parser(
        "registry", help="Inspect profiles, verify weights, or record timing evidence"
    )
    registry.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "registry":
        from model_registry import main as registry_main

        return registry_main(args.arguments)
    if args.action == "observe":
        os.execv(
            sys.executable,
            [
                sys.executable,
                str(PROJECT / "scripts/observe.py"),
                "--port",
                str(args.port),
            ],
        )
    if args.action in ("pilot", "results"):
        if args.action == "pilot":
            argv = [
                str(PROJECT / ".venv/bin/python"),
                str(PROJECT / "scripts/launch_pilot.py"),
                "--profile",
                args.profile,
                "--output",
                str(args.output),
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
            if args.dry_run:
                argv.append("--dry-run")
        else:
            argv = [
                sys.executable,
                str(PROJECT / "scripts/summarize_runs.py"),
                *map(str, args.campaigns),
            ]
            if args.report:
                argv.extend(["--report", str(args.report)])
        os.execv(argv[0], argv)
    if args.action == "doctor":
        if args.report and args.report.exists():
            parser.error("Report exists; choose a fresh path")
        result = doctor(args.probe_write)
        if args.report:
            with args.report.open("x") as stream:
                json.dump(result, stream, indent=2)
                stream.write("\n")
        for name, passed in result["checks"].items():
            print(f"{'OK' if passed else 'FAIL'} {name}")
        if not args.probe_write:
            print("Bulk write access untested; use --probe-write to check it.")
        print("This is an access check, not a candidate sandbox validation.")
        return int(args.require_access and not result["passed"])
    if args.action == "setup":
        root = prepare_storage()
        env = os.environ | {"UV_CACHE_DIR": str(root / "cache/uv")}
        lock_command = (
            ["uv", "lock", "--check"]
            if (PROJECT / "uv.lock").exists()
            else ["uv", "lock", "--python", sys.executable]
        )
        commands = [
            lock_command,
            ["uv", "sync", "--locked", "--python", sys.executable],
        ]
    else:
        env = os.environ.copy()
        commands = [
            ["ruff", "check", "scripts", "tasks", "tests"],
            ["ruff", "format", "--check", "scripts", "tasks", "tests"],
            [
                str(PROJECT / ".venv/bin/python")
                if (PROJECT / ".venv/bin/python").exists()
                else sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-q",
            ],
            [sys.executable, "scripts/check_fixtures.py"],
        ]
    for argv in commands:
        result = subprocess.run(argv, cwd=PROJECT, env=env, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"lab: {error}", file=sys.stderr)
        raise SystemExit(1) from error
