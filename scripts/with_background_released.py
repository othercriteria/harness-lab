"""Gate idle background Ollama clients around a restoring GPU transaction."""

import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import with_ollama_released as lifecycle

CONTROL = "/run/current-system/sw/bin/ollama-background"
UNITS = (
    "ollama-background.target",
    "ollama-background-gate.service",
    "weather-emoji.timer",
    "weather-emoji.service",
)


def state():
    states = {}
    for unit in UNITS:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=LoadState,ActiveState,SubState"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        states[unit] = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        if states[unit]["LoadState"] != "loaded":
            raise RuntimeError(f"Unit unavailable: {unit}")
    return states


def execute(command, output, gpu_lock_fd, command_timeout=1800):
    output.mkdir(parents=True, exist_ok=False)
    original = state()
    lifecycle.durable_json(output / "before.json", original)
    control_source = Path(CONTROL).read_bytes()
    (output / "control.sh").write_bytes(control_source)
    source = Path(__file__).read_bytes()
    (output / "wrapper.py").write_bytes(source)
    active = [original[u]["ActiveState"] for u in UNITS[:3]]
    if active == ["active"] * 3:
        was_on = True
    elif active == ["inactive"] * 3:
        was_on = False
    else:
        raise RuntimeError("Mixed/transitioning background group; no changes made")
    if original[UNITS[-1]]["ActiveState"] != "inactive":
        raise RuntimeError(
            "Background request active or failed; wait for an idle group"
        )
    connections = lifecycle.connections()
    lifecycle.durable_json(output / "connections-before.json", connections)
    if connections["stdout"].strip():
        raise RuntimeError("Ollama has established connections; no changes made")
    lifecycle.durable_json(
        output / "recovery-plan.json",
        {
            "original": original,
            "restore_argv": [CONTROL, "start"] if was_on else None,
            "control_sha256": hashlib.sha256(control_source).hexdigest(),
            "wrapper_sha256": hashlib.sha256(source).hexdigest(),
        },
    )
    result = {"ok": False, "stop_attempted": False, "restored": False}
    try:
        if state() != original:
            raise RuntimeError("Background states changed during preflight")
        if was_on:
            result["stop_attempted"] = True
            subprocess.run([CONTROL, "stop"], check=True, timeout=30)
            stopped = state()
            lifecycle.durable_json(output / "stopped.json", stopped)
            if any(stopped[u]["ActiveState"] != "inactive" for u in UNITS):
                raise RuntimeError("Background group did not stop")
        result["command_exit_code"] = lifecycle.run_owned(
            command, output, command_timeout, 600, gpu_lock_fd=gpu_lock_fd
        )
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        result["owned_cleanup_failed"] = isinstance(error, lifecycle.OwnedCleanupFailed)
    finally:
        with lifecycle.ignore_cancellation():
            try:
                if result.get("owned_cleanup_failed"):
                    raise RuntimeError(
                        "Restoration deferred: owned process cleanup unverified; use recovery-plan.json after stopping it"
                    )
                if result["stop_attempted"]:
                    subprocess.run([CONTROL, "start"], check=True, timeout=30)
                until = time.monotonic() + 60
                while True:
                    current = state()
                    if current == original or time.monotonic() >= until:
                        break
                    time.sleep(1)
                lifecycle.durable_json(output / "after.json", current)
                result["restored"] = current == original
            except BaseException as error:
                result["restore_error"] = str(error)
            result["ok"] = (
                result.get("command_exit_code") == 0
                and "error" not in result
                and result["restored"]
            )
            lifecycle.durable_json(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--command-timeout", type=int, default=1800)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(lifecycle.BULK / "runs"):
        parser.error("Use a fresh project bulk run directory")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide a command after --")
    with lifecycle.gpu_experiment_lock() as lock:

        def cancelled(signum, frame):
            raise lifecycle.Cancelled(signum)

        previous = {
            sig: signal.signal(sig, cancelled) for sig in lifecycle.CANCELLATION_SIGNALS
        }
        try:
            result = execute(command, output, lock.fileno(), args.command_timeout)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    print(json.dumps(result))
    return int(not result["ok"])


if __name__ == "__main__":
    sys.exit(main())
