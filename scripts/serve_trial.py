"""Pinned local server owner; called only inside the guarded restoring lifecycle."""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import with_ollama_released as lifecycle
from control import RunCancelled, cancellation
from model_registry import record_campaign, verify_weight
from protocol import (
    admit_tasks,
    load_protocol,
    profiles,
    protocols,
    server_resources,
    tasks,
)
from sandbox import protected_cleanup, write_json

PROJECT = Path(__file__).resolve().parents[1]
MODEL_STORAGE_ROOTS = (
    Path("/bulk/dlk/big-local-models"),
    Path("/bulk/dlk/local-harness"),
)


def weight_path(artifact, file):
    """Resolve pinned weights in sibling or project bulk; never task workspaces."""
    root = Path(artifact.get("storage_root", str(MODEL_STORAGE_ROOTS[0])))
    if root not in MODEL_STORAGE_ROOTS:
        raise ValueError("Model storage must use an authorized bulk root")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", artifact["id"]) or not re.fullmatch(
        r"[0-9a-f]{40}", artifact["revision"]
    ):
        raise ValueError("Invalid model identity or immutable revision")
    relative = Path(file["path"])
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("Weight filename escapes model storage")
    directory = root / "models" / artifact["id"] / artifact["revision"]
    path = directory / relative
    if not path.resolve().is_relative_to(
        directory
    ) or not directory.resolve().is_relative_to(root / "models"):
        raise ValueError("Weight symlink escapes model storage")
    return path


def verify_profile_weights(profile, *, mode, guard=lambda: None):
    """Verify each model independently, including an optional single-file draft."""
    draft_flags = {
        "--spec-draft-model",
        "--model-draft",
        "-md",
        "--spec-draft-hf",
        "--hf-repo-draft",
        "-hfd",
        "-hfrd",
    }
    if any(arg.split("=", 1)[0] in draft_flags for arg in profile["server_args"]):
        raise ValueError("Declare draft_artifact instead of a raw draft model path")
    artifacts = {"target": profile["artifact"]}
    if "draft_artifact" in profile:
        draft = profile["draft_artifact"]
        if not isinstance(draft, dict) or len(draft.get("files", [])) != 1:
            raise ValueError("draft_artifact requires exactly one pinned weight file")
        artifacts["draft"] = draft
    verified = {}
    for role, artifact in artifacts.items():
        if not artifact["files"]:
            raise ValueError("Model artifact has no weight files")
        verified[role] = [
            verify_weight(weight_path(artifact, file), file, mode=mode, guard=guard)
            for file in artifact["files"]
        ]
    return verified


def verified_model_args(weights):
    """Only paths from completed verification may become backend model arguments."""
    args = ["--model", weights["target"][0]["path"]]
    if "draft" in weights:
        args.extend(["--spec-draft-model", weights["draft"][0]["path"]])
    return args


def local_json(origin, path, timeout=2):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(origin + path, timeout=timeout) as response:
        return json.load(response)


def resources():
    memory = {
        line.split(":")[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
    }
    vm = dict(line.split() for line in Path("/proc/vmstat").read_text().splitlines())
    return {
        "time": time.time(),
        "available": memory["MemAvailable"],
        "swap_out_bytes": int(vm["pswpout"]) * os.sysconf("SC_PAGE_SIZE"),
    }


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def require_safe_trial(trial, returncode):
    """Only ordinary completed task outcomes may precede another trial."""
    path = trial / "summary.json"
    if not path.exists():
        raise RuntimeError("Trial exited without summary")
    summary = json.loads(path.read_text())
    if "unsafe_cleanup" in summary:
        raise RuntimeError(
            f"Campaign aborted: unsafe cleanup in {trial}: {summary['unsafe_cleanup']}"
        )
    if returncode not in (0, 1):
        raise RuntimeError(
            f"Campaign aborted: abnormal trial exit {returncode} in {trial}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=profiles(), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--tasks", nargs="+", choices=tasks(), default=["config-overlay"]
    )
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
    if not os.environ.get("BIG_MODELS_GPU_LOCK_FD"):
        parser.error("Requires inherited canonical GPU lock from lifecycle owner")
    output = args.output.resolve()
    if not output.is_relative_to("/bulk/dlk/local-harness/runs"):
        parser.error("Output must be in project bulk")
    output.mkdir(parents=True, exist_ok=False)
    profile = json.loads((PROJECT / "configs/servers.json").read_text())[args.profile]
    allowances = server_resources(profile)
    write_json(output / "server-resources.json", allowances)
    context = int(
        profile["server_args"][profile["server_args"].index("--ctx-size") + 1]
    )
    if context != limits["context_capacity_tokens"]:
        raise ValueError("Server context differs from protocol capacity")
    write_json(output / "protocol.json", limits)
    write_json(output / "profile.json", profile)
    write_json(output / "sampling.json", profile["sampling"])
    (output / "server-owner.py").write_bytes(Path(__file__).read_bytes())
    baseline = resources()
    write_json(output / "resources-before.json", baseline)
    if baseline["available"] < allowances["minimum_available_gib"] * 1024**3:
        raise RuntimeError("Available RAM is below the profile admission requirement")
    record = {
        "profile": args.profile,
        "completed": False,
        "server_stopped": False,
        "trials": [],
    }
    server = client = None
    log = None
    telemetry = (output / "telemetry.jsonl").open("w")

    def guard():
        current = resources()
        telemetry.write(json.dumps(current) + "\n")
        telemetry.flush()
        if current["available"] < 32 * 1024**3:
            raise RuntimeError("Available RAM fell below 32 GiB")
        if current["swap_out_bytes"] - baseline["swap_out_bytes"] > 128 * 1024**2:
            raise RuntimeError("Global swap-out guard exceeded 128 MiB")
        if local_json("http://127.0.0.1:11434", "/api/ps").get("models"):
            raise RuntimeError(
                "External Ollama residency detected during exclusive trial"
            )

    with lifecycle.gpu_experiment_lock(), cancellation():
        try:
            guard()
            verification_started = time.monotonic()
            artifact = profile["artifact"]
            weights = verify_profile_weights(
                profile, mode=args.weight_verification, guard=guard
            )
            write_json(output / "verified-weights.json", weights["target"])
            if "draft" in weights:
                write_json(output / "verified-draft-weights.json", weights["draft"])
            record["weight_verification_mode"] = args.weight_verification
            record["weight_verification_seconds"] = (
                time.monotonic() - verification_started
            )
            binary = Path(profile["binary"])
            if (
                hashlib.sha256(binary.read_bytes()).hexdigest()
                != profile["binary_sha256"]
            ):
                raise RuntimeError("Backend binary hash mismatch")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            origin = f"http://127.0.0.1:{port}"
            argv = [
                str(binary),
                *verified_model_args(weights),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--alias",
                artifact["id"],
                *profile["server_args"],
            ]
            write_json(
                output / "launch.json",
                {
                    "argv": argv,
                    "origin": origin,
                    "binary_sha256": profile["binary_sha256"],
                    "backend_revision": profile["backend_revision"],
                    "note": "See verified-weights.json for full-scan versus metadata reuse; full scans may warm storage pages",
                },
            )
            env = os.environ | {
                "LD_LIBRARY_PATH": "/run/opengl-driver/lib:"
                + os.environ.get("LD_LIBRARY_PATH", "")
            }
            log = (output / "server.log").open("wb")
            load_started = time.monotonic()
            server = subprocess.Popen(
                argv, stdout=log, stderr=subprocess.STDOUT, env=env, close_fds=True
            )
            write_json(output / "server-pid.json", {"pid": server.pid})
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Server exited during loading")
                guard()
                try:
                    if local_json(origin, "/health").get("status") == "ok":
                        break
                except (OSError, ValueError):
                    pass
                if (
                    time.monotonic() - load_started
                    > allowances["startup_timeout_seconds"]
                ):
                    raise RuntimeError("Server readiness timeout")
                time.sleep(1)
            record["model_load_seconds"] = time.monotonic() - load_started
            write_json(output / "props.json", local_json(origin, "/props"))
            for index, (seed, task) in enumerate(
                (s, t) for s in args.seeds for t in args.tasks
            ):
                guard()
                trial = output / f"trial-{index:02d}-{task}"
                command = [
                    str(PROJECT / ".venv/bin/python"),
                    str(PROJECT / "scripts/run_trial.py"),
                    "--task",
                    task,
                    "--output",
                    str(trial),
                    "--origin",
                    origin,
                    "--model",
                    artifact["id"],
                    "--sampling",
                    str(output / "sampling.json"),
                    "--protocol",
                    args.protocol,
                    "--seed",
                    str(seed),
                    "--split",
                    args.split,
                ]
                with (output / f"client-{index:02d}.log").open("wb") as client_log:
                    trial_started = time.monotonic()
                    client = subprocess.Popen(
                        command,
                        env=os.environ
                        | {"HARNESS_DISPATCH_MONOTONIC": str(trial_started)},
                        stdout=client_log,
                        stderr=subprocess.STDOUT,
                        close_fds=True,
                    )
                    while client.poll() is None:
                        guard()
                        if server.poll() is not None:
                            raise RuntimeError("Server exited during trial")
                        if (
                            time.monotonic() - trial_started
                            > limits["task_wall_seconds"] + 30
                        ):
                            raise RuntimeError(
                                "Trial process exceeded cleanup deadline"
                            )
                        time.sleep(1)
                    record["trials"].append(
                        {
                            "task": task,
                            "seed": seed,
                            "returncode": client.returncode,
                            "path": str(trial),
                            "process_wall_seconds": time.monotonic() - trial_started,
                        }
                    )
                    require_safe_trial(trial, client.returncode)
            record["completed"] = True
        except (Exception, RunCancelled) as error:
            record["error"] = {"type": type(error).__name__, "message": str(error)}
        finally:
            with protected_cleanup():
                stop(client)
                stop(server)
                record["server_stopped"] = server is None or server.poll() is not None
                record["client_stopped"] = client is None or client.poll() is not None
                if log:
                    log.close()
                telemetry.close()
                record["resources_after"] = resources()
                write_json(output / "summary.json", record)
                # Include startup failures and finish bookkeeping before a pending
                # cancellation is delivered on leaving protected cleanup.
                try:
                    registry_receipt = record_campaign(output.parent)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    # Registry bookkeeping cannot change an experiment's outcome.
                    registry_receipt = {
                        "error": str(error),
                        "type": type(error).__name__,
                    }
                write_json(output / "registry-receipt.json", registry_receipt)
    print(json.dumps(record))
    return int(
        not (
            record["completed"]
            and record["server_stopped"]
            and record["client_stopped"]
        )
    )


if __name__ == "__main__":
    sys.exit(main())
