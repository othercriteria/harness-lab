"""Own the pinned endpoint across both tasks inside the Lab's restoring GPU transaction."""

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from prepare import FOLLOWUP, ORIGINAL, TASKS

EXAMPLE = Path(__file__).resolve().parent
LAB = EXAMPLE.parents[1]
sys.path.insert(0, str(LAB / "scripts"))

PROFILE = "qwen38-27b-ranalayout-32k-temp06-dflash3-fit2304-dio"


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def run_client(argv, env, log_path, timing_path):
    with log_path.open("wb") as log:
        started = time.monotonic()
        result = subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        elapsed = time.monotonic() - started
    save(
        timing_path,
        {
            "dispatch_through_client_exit_seconds": elapsed,
            "returncode": result.returncode,
        },
    )
    result.check_returncode()


def run(root, label, agent="terminus-2"):
    from control import cancellation, defer_launch_signals
    from serve_trial import (
        local_json,
        stop,
        verified_model_args,
        verify_profile_weights,
    )
    from server_endpoint import owned_listener, process_identity
    from with_ollama_released import gpu_experiment_lock

    single_task = agent in TASKS
    if not single_task and agent not in {"terminus-2", "worker", "followup", "timing"}:
        raise ValueError("Unknown Harbor agent")
    if "BIG_MODELS_GPU_LOCK_FD" not in os.environ:
        raise RuntimeError("Launch through the restoring GPU transaction")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", label):
        raise ValueError("Use a fresh lowercase session label with optional hyphens")
    output = root / "sessions" / label
    output.mkdir(parents=True, exist_ok=False)
    profile = json.loads((LAB / "configs/servers.json").read_text())[PROFILE]
    binary = Path(profile["binary"])
    if hashlib.sha256(binary.read_bytes()).hexdigest() != profile["binary_sha256"]:
        raise ValueError("Backend binary differs from the selected profile")
    weights = verify_profile_weights(profile, mode="metadata")
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
        profile["artifact"]["id"],
        *profile["server_args"],
    ]
    save(output / "launch.json", {"profile": PROFILE, "argv": argv, "weights": weights})
    backend_env = os.environ | {
        "LD_LIBRARY_PATH": "/run/opengl-driver/lib:"
        + os.environ.get("LD_LIBRARY_PATH", "")
    }
    client_env = {
        "HOME": str(root / "controller-home"),
        "PATH": os.environ["PATH"],
        "HARBOR_SMOKE_ROOT": str(root),
        "OPENAI_API_KEY": "local-placeholder",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "HARBOR_TELEMETRY": "0",
    }
    with (
        (output / "server.log").open("wb") as log,
        gpu_experiment_lock(),
        cancellation(),
    ):
        server = None
        try:
            with defer_launch_signals():
                server = subprocess.Popen(
                    argv, stdout=log, stderr=subprocess.STDOUT, env=backend_env
                )
            identity = process_identity(server.pid)
            started = time.monotonic()
            while server.poll() is None and time.monotonic() - started < 120:
                if owned_listener(identity, port):
                    try:
                        if local_json(origin, "/health")["status"] == "ok":
                            break
                    except OSError:
                        pass
                time.sleep(0.5)
            else:
                raise RuntimeError("Backend failed to become ready")
            save(
                output / "ready.json",
                {
                    "seconds": time.monotonic() - started,
                    "owner": owned_listener(identity, port),
                },
            )
            schedule = [(task, agent) for task in ORIGINAL]
            timing = agent == "timing" or single_task
            followup = agent == "followup" or timing
            if single_task:
                schedule = [(agent, runner) for runner in ("worker", "terminus-2")]
            elif followup:
                first, second = (
                    ("fix-git", "log-summary-date-ranges") if timing else FOLLOWUP
                )
                schedule = [
                    (first, "worker"),
                    (first, "terminus-2"),
                    (second, "terminus-2"),
                    (second, "worker"),
                ]
            for task, agent in schedule:
                name = f"h{79 if agent == 'worker' else 78}-{task}-{label}"
                if not owned_listener(identity, port):
                    raise RuntimeError("Owned backend listener disappeared")
                log_name = name if followup else task
                run_client(
                    [
                        root / ".venv/bin/python",
                        EXAMPLE / "trial.py",
                        task,
                        agent,
                        name,
                        origin,
                        *(["--task-timeout"] if timing else []),
                        *(["--prepared-images"] if single_task else []),
                    ],
                    client_env,
                    output / f"{log_name}.log",
                    output / f"{name}.client-time.json",
                )
                result = json.loads(
                    (root / "trials" / name / "result.json").read_text()
                )
                failure = result.get("exception_info")
                if failure and failure["exception_type"] != "AgentTimeoutError":
                    raise RuntimeError(f"Inspect {name} before the next attempt")
        finally:
            stop(server)
            if server is not None:
                save(output / "server-closed.json", {"returncode": server.returncode})


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve(), *sys.argv[2:])
