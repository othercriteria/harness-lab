#!/usr/bin/env python3
"""Temporarily release the idle gpu-voice group around one restoring GPU command.

Use the ordinary-user gpu-voice {start|stop} host affordance; no sudo or individual
unit controls are invoked. Example: --output BULK/FRESH -- COMMAND [ARG ...].
The target and all three members must be either fully active, or fully off
(inactive/failed). A mixed active group cannot be restored exactly through the
group-only control and is refused before mutation. An existing off group,
including failed members, stays off without resetting failures or starting units.

Established host connections on 10300/8881/10210 and Kokoro container connections
on 8880 cause refusal. Checks cannot atomically prevent a new client from racing
the next control call. Restoration verifies original ActiveState/SubState and,
for an initially active group, TCP readiness of all three services. Warmed caches,
GPU allocation and application-internal state cannot be reconstructed.

The shared GPU lock spans stop, child cleanup and restoration. Nested Ollama and
smoke wrappers inherit it. SIGINT/SIGTERM/SIGHUP trigger owned cleanup before
group restoration. SIGKILL, host failure, or denied controls may require replaying
the durable recovery plan. Wrapper/helper/control sources and hashes are saved
before any mutation. A partial group stop is recovered with one group start;
individual member states are never forced through a different privilege path.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import with_ollama_released as lifecycle

BULK = lifecycle.BULK
SOURCE_PATH = Path(__file__).resolve()
SOURCE = SOURCE_PATH.read_bytes()
TARGET = "gpu-voice.target"
CONTROL_PATH = Path("/run/current-system/sw/bin/gpu-voice")
UNITS = {
    "wyoming-faster-whisper-default.service": 10300,
    "docker-kokoro.service": 8881,
    "wyoming-kokoro.service": 10210,
}


def systemctl(action, unit, timeout=180):
    if unit not in (TARGET, *UNITS) or action != "show":
        raise ValueError("Unit access is read-only; group changes require gpu-voice")
    argv = ["systemctl", "--no-ask-password", action, unit]
    if action == "show":
        argv += [
            "--no-pager",
            "--property=ActiveState,SubState,MainPID,UnitFileState,InvocationID",
        ]
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    data = {
        "argv": argv,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if action == "show" and result.returncode == 0:
        data["properties"] = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
    return data


def inspected(argv):
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=15, check=False
    )
    return {
        "argv": argv,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def established_container_connections(text):
    matching = []
    for line in text.splitlines():
        fields = line.split()
        if (
            len(fields) >= 4
            and fields[3] == "01"
            and any(
                address.rsplit(":", 1)[-1].upper() == "22B0" for address in fields[1:3]
            )
        ):
            matching.append(line)
    return matching


def idle_snapshot(check_container):
    host = inspected(
        [
            "ss",
            "-Htn",
            "state",
            "established",
            "( sport = :10300 or dport = :10300 or sport = :8881 or dport = :8881 or sport = :10210 or dport = :10210 )",
        ]
    )
    container = None
    if check_container:
        container = inspected(
            ["docker", "exec", "kokoro", "cat", "/proc/net/tcp", "/proc/net/tcp6"]
        )
    return {"host": host, "container": container}


def require_idle(snapshot):
    for record in (snapshot["host"], snapshot["container"]):
        if record is not None and record["returncode"] != 0:
            raise RuntimeError(f"Cannot establish speech idleness: {record}")
    if snapshot["host"]["stdout"].strip():
        raise RuntimeError(
            "Established host speech connection; coordinate before retrying"
        )
    container = snapshot["container"]
    if container and established_container_connections(container["stdout"]):
        raise RuntimeError(
            "Established Kokoro container connection; coordinate before retrying"
        )


def port_ready(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def state_pair(state):
    props = state["properties"]
    return props["ActiveState"], props["SubState"]


def control(action, executable, timeout=180):
    if action not in {"start", "stop"}:
        raise ValueError("Only group start/stop are permitted")
    argv = [executable, action]
    completed = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def capture_control(output):
    executable = CONTROL_PATH.resolve(strict=True)
    source = executable.read_bytes()
    with (output / "gpu-voice-source.sh").open("xb") as stream:
        stream.write(source)
        stream.flush()
        os.fsync(stream.fileno())
    record = {
        "original_path": str(CONTROL_PATH),
        "executable": str(executable),
        "sha256": hashlib.sha256(source).hexdigest(),
        "snapshot_path": "gpu-voice-source.sh",
        "units": {},
    }
    for unit in (TARGET, *UNITS):
        path = Path("/etc/systemd/system") / unit
        data = path.read_bytes()
        record["units"][unit] = {
            "source_path": str(path.resolve()),
            "source": data.decode(),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    lifecycle.durable_json(output / "gpu-voice-control.json", record)
    return record


def classify_group(states):
    active = [state_pair(states[unit])[0] for unit in (TARGET, *UNITS)]
    if all(value == "active" for value in active):
        return "on"
    if all(value in {"inactive", "failed"} for value in active):
        return "off"
    raise RuntimeError(
        "Mixed or transitioning gpu-voice group cannot be restored exactly with group-only controls"
    )


def execute(
    command,
    output,
    gpu_lock_fd,
    service_timeout=180,
    command_timeout=3600,
    shutdown_timeout=480,
):
    result = {
        "ok": False,
        "command": command,
        "command_exit_code": None,
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "stop_attempted": [],
        "restoration": [],
    }
    original = {}
    controls = None
    sequence = 0

    def save(label, data):
        nonlocal sequence
        sequence += 1
        lifecycle.durable_json(output / f"{sequence:03d}-{label}.json", data)

    def inspect_all():
        states = {}
        for unit in (TARGET, *UNITS):
            state = systemctl("show", unit, timeout=15)
            if state["returncode"]:
                raise RuntimeError(f"Cannot inspect {unit}: {state}")
            states[unit] = state
        return states

    def same_states(states):
        return all(
            state_pair(states[unit]) == state_pair(state)
            for unit, state in original.items()
        )

    def ready(states):
        return same_states(states) and all(port_ready(port) for port in UNITS.values())

    def idle(label):
        reading = idle_snapshot(result.get("group_before") == "on")
        save(label, reading)
        require_idle(reading)

    try:
        with (output / "speech-wrapper-source.py").open("xb") as stream:
            stream.write(SOURCE)
            stream.flush()
            os.fsync(stream.fileno())
        result["source_sha256"] = hashlib.sha256(SOURCE).hexdigest()
        lifecycle.durable_json(
            output / "speech-wrapper-source.json",
            {
                "original_path": str(SOURCE_PATH),
                "snapshot_path": "speech-wrapper-source.py",
                "sha256": result["source_sha256"],
                "python": sys.version,
                "argv": sys.argv,
            },
        )
        result["lifecycle_helper_sha256"] = lifecycle.snapshot_source(output)
        controls = capture_control(output)
        result["control_sha256"] = controls["sha256"]
        original = inspect_all()
        save("states-before", original)
        result["group_before"] = classify_group(original)
        lifecycle.durable_json(
            output / "recovery-plan.json",
            {
                "states": original,
                "group_before": result["group_before"],
                "control": controls,
                "stop_argv": [controls["executable"], "stop"],
                "restore_argv": [controls["executable"], "start"]
                if result["group_before"] == "on"
                else None,
                "policy": "An initially off group is never started. An initially fully active group is restored once with gpu-voice start if stop was attempted.",
                "limitations": __doc__,
            },
        )
        idle("connections-before")
        current = inspect_all()
        save("states-pre-command", current)
        if any(
            current[unit]["properties"] != state["properties"]
            for unit, state in original.items()
        ):
            raise RuntimeError(
                "gpu-voice state changed during preflight; refusing group control"
            )
        if result["group_before"] == "on":
            idle("connections-pre-stop")
            result["stop_attempted"].append(
                TARGET
            )  # A timed-out group stop may have partly succeeded.
            response = control("stop", controls["executable"], timeout=service_timeout)
            save("group-stop", response)
            if response["returncode"]:
                raise RuntimeError(f"Cannot stop gpu-voice group: {response['stderr']}")
            stopped = inspect_all()
            save("states-stop-requested", stopped)
            stop_deadline = time.monotonic() + service_timeout
            while any(
                state_pair(state)[0] not in {"inactive", "failed"}
                for state in stopped.values()
            ):
                if time.monotonic() >= stop_deadline:
                    raise RuntimeError("gpu-voice members did not finish stopping")
                time.sleep(0.2)
                stopped = inspect_all()
            save("states-stopped", stopped)
            if classify_group(stopped) != "off":
                raise RuntimeError("gpu-voice group still active after stop")
        result["command_exit_code"] = lifecycle.run_owned(
            command, output, command_timeout, shutdown_timeout, gpu_lock_fd=gpu_lock_fd
        )
    except BaseException as error:  # noqa: BLE001 - All failures must reach restoration.
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        if isinstance(error, lifecycle.Cancelled):
            result["cancelled_signal"] = error.signum
        if isinstance(error, lifecycle.OwnedCleanupFailed):
            result["owned_cleanup_failed"] = True
    finally:
        with lifecycle.ignore_cancellation():
            if result.get("owned_cleanup_failed"):
                result["restoration_blocked"] = (
                    "Owned command cleanup failed; stop its recorded session before replaying recovery-plan.json."
                )
            elif result["stop_attempted"]:
                restoration = {"target": TARGET, "ok": False}
                try:
                    current = inspect_all()
                    if ready(current):
                        save("states-already-restored", current)
                        restoration.update(ok=True, tcp_ready=True, already_ready=True)
                    else:
                        response = control(
                            "start", controls["executable"], timeout=service_timeout
                        )
                        save("group-restore", response)
                        if response["returncode"]:
                            raise RuntimeError(
                                f"Cannot restore gpu-voice group: {response['stderr']}"
                            )
                        end = time.monotonic() + service_timeout
                        while True:
                            current = inspect_all()
                            if ready(current):
                                save("states-restored", current)
                                restoration.update(ok=True, tcp_ready=True)
                                break
                            if time.monotonic() >= end:
                                save("states-restore-timeout", current)
                                raise TimeoutError(
                                    "gpu-voice group did not recover original states and TCP readiness"
                                )
                            time.sleep(1)
                except BaseException as error:  # noqa: BLE001 - Preserve group restoration failures.
                    restoration["error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                result["restoration"].append(restoration)
            try:
                final = inspect_all()
                save("states-after", final)
                result["states_verified"] = bool(original) and same_states(final)
            except BaseException as error:  # noqa: BLE001 - Preserve verification failures.
                result["states_verified"] = False
                result["verification_error"] = str(error)
            result["ok"] = (
                "error" not in result
                and result["command_exit_code"] == 0
                and result["states_verified"]
                and all(item["ok"] for item in result["restoration"])
                and not result.get("restoration_blocked")
            )
            result["finished_at"] = datetime.datetime.now(datetime.UTC).isoformat()
            lifecycle.durable_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--service-timeout", type=float, default=180)
    parser.add_argument("--command-timeout", type=float, default=3600)
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=480,
        help="Allow nested model cleanup and Ollama restoration before speech restoration",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if os.geteuid() == 0:
        parser.error(
            "Run as the ordinary user through the gpu-voice affordance; no root or run-as mode is provided"
        )
    if not command or any(
        not math.isfinite(value) or value <= 0
        for value in (args.service_timeout, args.command_timeout, args.shutdown_timeout)
    ):
        parser.error("Provide a command after -- and positive finite deadlines")
    output = args.output.resolve()
    if not output.is_relative_to(BULK):
        parser.error("Evidence must remain under project bulk")
    output.mkdir(parents=True, exist_ok=False)
    parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    with lifecycle.gpu_experiment_lock() as gpu_lock:

        def cancelled(signum, frame):
            raise lifecycle.Cancelled(signum)

        previous = {
            sig: signal.signal(sig, cancelled) for sig in lifecycle.CANCELLATION_SIGNALS
        }
        try:
            result = execute(
                command,
                output,
                gpu_lock.fileno(),
                args.service_timeout,
                args.command_timeout,
                args.shutdown_timeout,
            )
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    print(json.dumps(result), flush=True)
    return (
        128 + result["cancelled_signal"]
        if result.get("cancelled_signal")
        else (0 if result["ok"] else 1)
    )


if __name__ == "__main__":
    sys.exit(main())
