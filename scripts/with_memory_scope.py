#!/usr/bin/env python3
"""Contain one command in an owned user memory scope; keep this observer outside.

Place this INSIDE service/Ollama restoration wrappers, immediately around the
runner. Default limits are 140 GiB charged memory, no new swap, with a 160 GiB
MemAvailable admission floor. This is resource containment, not a security
sandbox. Shared page cache can be charged elsewhere; retain runner host guards.

A tiny anchor verifies readiness without launching the command, then holds the
scope open after command exit for final cgroup evidence. All processes retain
the caller's process group, so outer lifecycle cleanup still covers descendants.
No GPU calls, service state changes, cache dropping or explicit flock unlocks.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
import select
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

BULK = Path("/bulk/dlk/local-harness")
SOURCE = Path(__file__).resolve().read_bytes()
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
CGROUP_ROOT = Path("/sys/fs/cgroup")
CGROUP_FILES = (
    "memory.current",
    "memory.peak",
    "memory.max",
    "memory.swap.current",
    "memory.swap.max",
    "memory.events",
    "memory.events.local",
    "memory.stat",
    "memory.pressure",
    "cgroup.events",
    "cgroup.procs",
)
PROPERTIES = (
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "ControlGroup",
    "MemoryMax",
    "MemorySwapMax",
    "MemoryCurrent",
    "MemoryPeak",
    "MemorySwapPeak",
    "OOMPolicy",
    "RuntimeMaxUSec",
    "TimeoutStopUSec",
    "TasksCurrent",
    "InvocationID",
)


class Cancelled(Exception):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"Received signal {signum}")


def durable_json(path, value):
    """New evidence only: never overwrite an earlier outcome."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic publication without overwriting evidence.
    finally:
        temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextlib.contextmanager
def ignoring_cancellation():
    prior = {sig: signal.signal(sig, signal.SIG_IGN) for sig in SIGNALS}
    try:
        yield
    finally:
        for sig, handler in prior.items():
            signal.signal(sig, handler)


def systemctl(unit, *args):
    return subprocess.run(
        ["systemctl", "--user", *args, unit],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def properties(unit):
    response = systemctl(
        unit, "show", "--no-pager", "--property=" + ",".join(PROPERTIES)
    )
    return {
        "returncode": response.returncode,
        "stderr": response.stderr.strip(),
        "values": dict(
            line.split("=", 1) for line in response.stdout.splitlines() if "=" in line
        ),
    }


def cgroup_path(relative, unit):
    if not relative.startswith("/") or Path(relative).name != unit:
        raise RuntimeError(f"Unexpected owned scope cgroup: {relative!r}")
    path = (CGROUP_ROOT / relative.lstrip("/")).resolve()
    if not path.is_relative_to(CGROUP_ROOT.resolve()) or ".." in Path(relative).parts:
        raise RuntimeError("Scope cgroup escapes cgroup root")
    return path


def own_cgroup():
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return line[3:]
    raise RuntimeError("Unified cgroup v2 is required")


def cgroup_sample(path):
    result = {"monotonic": time.monotonic(), "files": {}, "errors": {}}
    for name in CGROUP_FILES:
        try:
            result["files"][name] = (path / name).read_text().strip()
        except OSError as error:
            result["errors"][name] = str(error)
    return result


def counters(sample):
    result = {}
    for line in sample.get("files", {}).get("memory.events", "").splitlines():
        key, value = line.split()
        result[key] = int(value)
    return result


def oom_evidence(samples, final_properties):
    observed = {}
    for sample in samples:
        for key, value in counters(sample).items():
            observed[key] = max(value, observed.get(key, 0))
    return {
        "maximum_observed_memory_events": observed,
        "oom_observed": bool(
            observed.get("oom", 0)
            or observed.get("oom_kill", 0)
            or final_properties.get("values", {}).get("Result") == "oom-kill"
        ),
        "event_counters_observed": bool(observed),
        "note": "A vanished cgroup may prevent a final read; zero last-observed counters do not prove no later OOM.",
    }


def validate_limits(snapshot, props, expected_bytes):
    files = snapshot["files"]
    actual = props["values"]
    if (
        files.get("memory.max") != str(expected_bytes)
        or files.get("memory.swap.max") != "0"
    ):
        raise RuntimeError(
            "Actual cgroup limits differ from requested memory/swap limits"
        )
    if (
        actual.get("MemoryMax") != str(expected_bytes)
        or actual.get("MemorySwapMax") != "0"
    ):
        raise RuntimeError(
            "User manager properties differ from requested memory/swap limits"
        )
    if actual.get("OOMPolicy") != "continue":
        raise RuntimeError("Scope OOM policy must retain observer-controlled cleanup")


def inherited_lock(root=Path("/bulk/dlk/big-local-models")):
    """Duplicate a validated caller lock; closing never releases their flock."""
    raw = os.environ.get("BIG_MODELS_GPU_LOCK_FD")
    if raw is None:
        return None
    original = int(raw)
    actual = os.fstat(original)
    expected = (root / "gpu-experiment.lock").stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise RuntimeError("Inherited GPU lock is not the canonical project lock")
    duplicate = os.dup(original)
    try:
        fcntl.flock(duplicate, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return duplicate
    except BaseException:
        os.close(duplicate)
        raise


def scope_argv(
    unit,
    memory_bytes,
    lifetime,
    anchor,
    output,
    control_fd,
    gpu_lock_fd,
    shutdown_timeout=45,
):
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--expand-environment=no",
        "--unit=" + unit,
        "--property=MemoryAccounting=yes",
        "--property=MemoryMax=" + str(memory_bytes),
        "--property=MemorySwapMax=0",
        "--property=OOMPolicy=continue",
        "--property=RuntimeMaxSec=" + str(math.ceil(lifetime)),
        "--property=TimeoutStopSec=" + str(math.ceil(shutdown_timeout)),
        "--",
        sys.executable,
        str(anchor),
        "--inside",
        str(output),
        str(control_fd),
        str(gpu_lock_fd if gpu_lock_fd is not None else -1),
    ]


def stop_direct(child, grace):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=10)


def inside(output, control_fd, gpu_lock_fd):
    """Trusted anchor: no command before parent handshake; no new process group."""
    config = json.loads((output / "launch.json").read_text())
    stop_requested = []
    for sig in SIGNALS:
        signal.signal(sig, lambda signum, frame: stop_requested.append(signum))
    child = None
    result_written = False
    durable_json(
        output / "anchor-ready.json",
        {
            "pid": os.getpid(),
            "cgroup": own_cgroup(),
            "process_group": os.getpgrp(),
        },
    )
    buffer = b""
    started = None
    try:
        while True:
            readable, _, _ = select.select([control_fd], [], [], 0.1)
            if readable:
                data = os.read(control_fd, 4096)
                if not data:  # Observer died: stop runner; RuntimeMax is last fallback.
                    break
                buffer += data
                while b"\n" in buffer:
                    message, buffer = buffer.split(b"\n", 1)
                    if message == b"start" and child is None:
                        if stop_requested:
                            break
                        env = {**os.environ}
                        env.pop("BIG_MODELS_GPU_LOCK_FD", None)
                        pass_fds = ()
                        if gpu_lock_fd >= 0:
                            env["BIG_MODELS_GPU_LOCK_FD"] = str(gpu_lock_fd)
                            pass_fds = (gpu_lock_fd,)
                        with (output / "command.log").open("xb") as log:
                            child = subprocess.Popen(
                                config["command"],
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                env=env,
                                pass_fds=pass_fds,
                            )
                        started = time.monotonic()
                        durable_json(
                            output / "child-started.json",
                            {
                                "pid": child.pid,
                                "monotonic": started,
                                "process_group": os.getpgid(child.pid),
                            },
                        )
                    elif message == b"release":
                        return 0
                    else:
                        raise RuntimeError(
                            "Unexpected or repeated anchor control message"
                        )
            if stop_requested:
                break
            if child is not None and not result_written:
                timed_out = time.monotonic() - started > config["command_timeout"]
                if timed_out:
                    stop_direct(child, config["shutdown_timeout"])
                if child.poll() is not None:
                    durable_json(
                        output / "child-result.json",
                        {
                            "returncode": child.returncode,
                            "timed_out": timed_out,
                            "elapsed_seconds": time.monotonic() - started,
                        },
                    )
                    result_written = True
    finally:
        with ignoring_cancellation():
            stop_direct(child, config["shutdown_timeout"])
            os.close(control_fd)
    return 0


def populated(path):
    try:
        data = dict(
            line.split() for line in (path / "cgroup.events").read_text().splitlines()
        )
        return data.get("populated") == "1"
    except FileNotFoundError:
        return False


def inactive(props):
    values = props["values"]
    return (
        (
            props["returncode"] == 0
            and values.get("ActiveState") in ("inactive", "failed")
        )
        or values.get("LoadState") == "not-found"
        or "could not be found" in props.get("stderr", "")
    )


def cleanup(unit, child, path, grace):
    """Try every bounded cleanup stage even if an earlier manager call fails."""
    actions = []
    errors = []

    def act(*args):
        action = {"arguments": list(args)}
        try:
            response = systemctl(unit, *args)
            action.update(
                returncode=response.returncode, stderr=response.stderr.strip()
            )
        except (OSError, subprocess.SubprocessError) as error:
            action["error"] = repr(error)
        actions.append(action)

    act("kill", "--kill-whom=all", "--signal=SIGTERM")
    until = time.monotonic() + grace
    while time.monotonic() < until:
        try:
            if child.poll() is not None and path is not None and not populated(path):
                break
            if path is None and child.poll() is not None and inactive(properties(unit)):
                break
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(repr(error))
            break
        time.sleep(0.1)
    try:
        needs_kill = child.poll() is None or path is None or populated(path)
    except OSError as error:
        errors.append(repr(error))
        needs_kill = True
    if needs_kill:
        act("kill", "--kill-whom=all", "--signal=SIGKILL")
    act("stop")
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired as error:
        errors.append(repr(error))
        # This Popen handle still owns the unreaped leader; no PID/group guessing.
        child.kill()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired as error:
            errors.append(repr(error))
    try:
        final = properties(unit)
        empty = path is None or not populated(path)
        # Missing path before readiness is safe only with manager proof of inactivity.
        clean = child.poll() is not None and empty and inactive(final)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        errors.append(repr(error))
        final, empty, clean = {}, None, False
    return {
        "verified": clean,
        "actions": actions,
        "errors": errors,
        "properties": final,
        "cgroup_empty_or_absent": empty,
        "anchor_returncode": child.returncode,
    }


WHOLE_COMMAND_GLOBAL_GUARD = {
    "minimum_available_memory_gib": 16,
    "maximum_swap_out_mib": 256,
    "maximum_memory_full_stall_fraction": 0.2,
    "consecutive_pressure_samples": 3,
    "poll_interval_seconds": 1,
}
GLOBAL_ATTRIBUTION = (
    "System-wide counters, not process- or scope-attributed. Scope swap=0 does "
    "not prevent another workload from swapping."
)


class WholeCommandGlobalGuardExceeded(RuntimeError):
    pass


def global_resource_sample(proc_root=Path("/proc")):
    """Read only the host counters needed by the optional outer guard."""
    memory = dict(
        line.split(":", 1) for line in (proc_root / "meminfo").read_text().splitlines()
    )
    vmstat = dict(
        line.split() for line in (proc_root / "vmstat").read_text().splitlines()
    )
    pressure = {}
    for line in (proc_root / "pressure/memory").read_text().splitlines():
        kind, *fields = line.split()
        pressure[kind] = dict(field.split("=", 1) for field in fields)
    result = {
        "monotonic": time.monotonic(),
        "available_bytes": int(memory["MemAvailable"].split()[0]) * 1024,
        "swap_out_pages": int(vmstat["pswpout"]),
        "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
        "memory_full_total_us": int(pressure["full"]["total"]),
    }
    if any(value < 0 for value in result.values()):
        raise RuntimeError("Invalid negative global resource counter")
    return result


def global_guard_observation(baseline, previous, current, pressure_streak):
    """Use cumulative swap since the pre-command gate; PSI uses each interval."""
    config = WHOLE_COMMAND_GLOBAL_GUARD
    elapsed = current["monotonic"] - previous["monotonic"]
    swap_pages = current["swap_out_pages"] - baseline["swap_out_pages"]
    stall_us = current["memory_full_total_us"] - previous["memory_full_total_us"]
    if (
        elapsed < 0
        or swap_pages < 0
        or current["swap_out_pages"] < previous["swap_out_pages"]
        or stall_us < 0
    ):
        raise RuntimeError("Global resource counters regressed")
    if current["page_size_bytes"] != baseline["page_size_bytes"]:
        raise RuntimeError("Global resource page size changed")
    fraction = stall_us / (elapsed * 1_000_000) if elapsed else 0.0
    swapped_mib = swap_pages * current["page_size_bytes"] / 2**20
    pressure_streak = (
        pressure_streak + 1
        if fraction > config["maximum_memory_full_stall_fraction"]
        else 0
    )
    reasons = []
    available_gib = current["available_bytes"] / 2**30
    if available_gib < config["minimum_available_memory_gib"]:
        reasons.append(
            {
                "limit": "minimum_available_memory_gib",
                "measured": available_gib,
                "threshold": config["minimum_available_memory_gib"],
            }
        )
    if swapped_mib > config["maximum_swap_out_mib"]:
        reasons.append(
            {
                "limit": "maximum_swap_out_mib",
                "measured": swapped_mib,
                "threshold": config["maximum_swap_out_mib"],
            }
        )
    if pressure_streak >= config["consecutive_pressure_samples"]:
        reasons.append(
            {
                "limit": "maximum_memory_full_stall_fraction",
                "measured": fraction,
                "threshold": config["maximum_memory_full_stall_fraction"],
                "consecutive_samples": pressure_streak,
            }
        )
    return {
        "sample": current,
        "swap_out_growth_mib": swapped_mib,
        "memory_full_stall_fraction": fraction,
        "pressure_streak": pressure_streak,
        "reasons": reasons,
    }


class WholeCommandGlobalGuard:
    """Outer observer; sampling never waits for bulk evidence writes."""

    def __init__(self, baseline):
        self.baseline = baseline
        self.previous = baseline
        self.observations = []
        self.pressure_streak = 0
        self.trigger = None
        self.triggered = threading.Event()
        self._stop = threading.Event()
        self.thread = None
        self.observe(baseline)

    def observe(self, sample):
        observation = global_guard_observation(
            self.baseline, self.previous, sample, self.pressure_streak
        )
        self.previous = sample
        self.pressure_streak = observation["pressure_streak"]
        self.observations.append(observation)
        if observation["reasons"] and self.trigger is None:
            self.trigger = {**observation, "attribution": GLOBAL_ATTRIBUTION}
            self.triggered.set()  # Relieve pressure before writing any evidence.
        return observation

    def start(self):
        self.raise_if_triggered()
        self.thread = threading.Thread(
            target=self._run, name="whole-command-global-guard", daemon=True
        )
        self.thread.start()

    def _run(self):
        try:
            while not self._stop.wait(
                WHOLE_COMMAND_GLOBAL_GUARD["poll_interval_seconds"]
            ):
                self.observe(global_resource_sample())
                if self.triggered.is_set():
                    return
        except Exception as error:  # noqa: BLE001 - fail closed on observer loss
            self.trigger = {
                "reasons": [{"limit": "observer_error", "error": repr(error)}],
                "attribution": GLOBAL_ATTRIBUTION,
            }
            self.triggered.set()

    def raise_if_triggered(self):
        if self.triggered.is_set():
            raise WholeCommandGlobalGuardExceeded(
                "Whole-command global resource guard stopped the owned scope; "
                "see whole-command-global-guard.json"
            )

    def finish(self, output):
        self._stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError("Whole-command resource observer did not stop")
        # A short command may finish between periodic samples. Capture its
        # cumulative swap/available result too, without inventing PSI intervals.
        try:
            self.observe(global_resource_sample())
        except Exception as error:  # noqa: BLE001 - persist observer failure
            if self.trigger is None:
                self.trigger = {
                    "reasons": [{"limit": "observer_error", "error": repr(error)}],
                    "attribution": GLOBAL_ATTRIBUTION,
                }
                self.triggered.set()
        with (output / "whole-command-global-samples.jsonl").open("x") as stream:
            for observation in self.observations:
                stream.write(json.dumps(observation) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        evidence = {
            "enabled": True,
            "configuration": WHOLE_COMMAND_GLOBAL_GUARD,
            "attribution": GLOBAL_ATTRIBUTION,
            "baseline": self.baseline,
            "baseline_phase": "outside contained child, before start gate",
            "coverage": "Entire contained command including receipt weight hashing",
            "observations": len(self.observations),
            "trigger": self.trigger,
            "sampling_note": (
                "Polling is not a reservation or hard host limit; hard cgroup "
                "limits remain active. Observations and cgroup telemetry are "
                "persisted after cleanup. Proc/manager/metadata operations can "
                "still delay main-thread response; this is not realtime control."
            ),
        }
        durable_json(output / "whole-command-global-guard.json", evidence)
        return evidence


def available_bytes():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("Cannot measure MemAvailable")


def supervise(
    output,
    command,
    memory_bytes,
    command_timeout,
    shutdown_timeout,
    sample_interval,
    minimum_available_bytes,
    gpu_lock_fd=None,
    whole_command_global_guard=False,
):
    """Called only with a fresh output and, optionally, an already validated FD."""
    unit = "big-model-memory-" + uuid.uuid4().hex + ".scope"
    available = available_bytes()
    if available < minimum_available_bytes:
        raise RuntimeError(
            f"MemAvailable {available} below admission floor {minimum_available_bytes}"
        )
    anchor = output / "scope-supervisor.py"
    anchor.write_bytes(SOURCE)
    lifetime = 60 + command_timeout + shutdown_timeout + 60
    read_fd, write_fd = os.pipe()
    child = None
    path = None
    samples = []
    failure = None
    outcome = None
    whole_guard = None
    whole_guard_evidence = None
    buffered_cgroup_samples = []
    scope_end_evidence = None
    after = {}
    cleanup_result = {"verified": True, "not_started": True}
    argv = scope_argv(
        unit,
        memory_bytes,
        lifetime,
        anchor,
        output,
        read_fd,
        gpu_lock_fd,
        shutdown_timeout,
    )
    durable_json(
        output / "launch.json",
        {
            "command": command,
            "unit": unit,
            "scope_argv": argv,
            "memory_max_bytes": memory_bytes,
            "memory_swap_max_bytes": 0,
            "available_bytes_before": available,
            "minimum_available_bytes": minimum_available_bytes,
            "command_timeout": command_timeout,
            "shutdown_timeout": shutdown_timeout,
            "sample_interval": sample_interval,
            "whole_command_global_guard": bool(whole_command_global_guard),
            "runtime_max_seconds": lifetime,
            "inherited_gpu_lock_fd": gpu_lock_fd,
            "source_sha256": hashlib.sha256(SOURCE).hexdigest(),
            "caller_process_group": os.getpgrp(),
            "recovery_commands": [
                [
                    "systemctl",
                    "--user",
                    "kill",
                    "--kill-whom=all",
                    "--signal=SIGKILL",
                    unit,
                ],
                ["systemctl", "--user", "stop", unit],
            ],
            "limitations": "MemoryMax bounds cgroup charges, not all model RSS, host usage or VRAM; retain host guards. No automatic restoration is performed here.",
        },
    )
    try:
        with (output / "scope.log").open("xb") as log:
            # Defer signal handling through Popen until we own its handle.
            pending = []
            prior = {
                sig: signal.signal(sig, lambda number, frame: pending.append(number))
                for sig in SIGNALS
            }
            try:
                child = subprocess.Popen(
                    argv,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    pass_fds=(read_fd,)
                    + (() if gpu_lock_fd is None else (gpu_lock_fd,)),
                )
            finally:
                for sig, handler in prior.items():
                    signal.signal(sig, handler)
            if pending:
                raise Cancelled(pending[0])
        os.close(read_fd)
        read_fd = -1
        deadline = time.monotonic() + 60
        while not (output / "anchor-ready.json").exists():
            if child.poll() is not None:
                raise RuntimeError(f"Scope exited before readiness: {child.returncode}")
            if time.monotonic() > deadline:
                raise TimeoutError("Scope readiness exceeded 60 seconds")
            time.sleep(0.05)
        ready = json.loads((output / "anchor-ready.json").read_text())
        if ready["pid"] != child.pid:
            raise RuntimeError("Scope anchor PID differs from owned systemd-run PID")
        if ready["process_group"] != os.getpgrp():
            raise RuntimeError("Scope anchor left outer lifecycle process group")
        path = cgroup_path(ready["cgroup"], unit)
        before = properties(unit)
        if before["values"].get("ControlGroup") != ready["cgroup"]:
            raise RuntimeError("Scope readiness cgroup differs from user manager")
        first = cgroup_sample(path)
        validate_limits(first, before, memory_bytes)
        durable_json(
            output / "scope-start.json", {"properties": before, "cgroup": first}
        )
        samples.append(first)
        if whole_command_global_guard:
            baseline = global_resource_sample()
            whole_guard = WholeCommandGlobalGuard(baseline)
            durable_json(
                output / "whole-command-global-baseline.json",
                {
                    "configuration": WHOLE_COMMAND_GLOBAL_GUARD,
                    "attribution": GLOBAL_ATTRIBUTION,
                    "sample": baseline,
                    "phase": "outside contained child, before start gate",
                },
            )
            whole_guard.start()
            whole_guard.raise_if_triggered()
        os.write(write_fd, b"start\n")
        # With host protection enabled, avoid bulk writes while the command
        # may need prompt relief. Existing samples are already retained in RAM.
        telemetry_context = (
            contextlib.nullcontext(None)
            if whole_guard is not None
            else (output / "cgroup-samples.jsonl").open("x")
        )
        with telemetry_context as telemetry:
            deadline = time.monotonic() + command_timeout + shutdown_timeout + 10
            while True:
                if whole_guard is not None:
                    whole_guard.raise_if_triggered()
                sample = cgroup_sample(path)
                samples.append(sample)
                events = counters(sample)
                if events.get("oom", 0) or events.get("oom_kill", 0):
                    raise RuntimeError("Owned scope reached its cgroup OOM limit")
                if telemetry is None:
                    buffered_cgroup_samples.append(sample)
                else:
                    telemetry.write(json.dumps(sample) + "\n")
                    telemetry.flush()
                if (output / "child-result.json").exists():
                    outcome = json.loads((output / "child-result.json").read_text())
                    break
                if child.poll() is not None:
                    raise RuntimeError(
                        f"Scope anchor exited before command result: {child.returncode}"
                    )
                if time.monotonic() > deadline:
                    raise TimeoutError("Scope command plus cleanup deadline exceeded")
                time.sleep(
                    min(sample_interval, 1)
                    if whole_guard is not None
                    else sample_interval
                )
    except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 - preserve any command/lifecycle failure
        failure = {"type": type(error).__name__, "message": str(error)}
        if isinstance(error, Cancelled):
            failure["signal"] = error.signum
    finally:
        with ignoring_cancellation():
            # Capture while anchor is alive, BEFORE releasing it / removing cgroup.
            try:
                after = properties(unit) if child is not None else {}
                last = cgroup_sample(path) if path is not None else None
                if last:
                    samples.append(last)
                scope_end_evidence = {"properties": after, "cgroup": last}
                if whole_guard is None:
                    durable_json(output / "scope-end.json", scope_end_evidence)
            except Exception as error:  # noqa: BLE001 - evidence errors must not skip cleanup
                failure = failure or {
                    "type": type(error).__name__,
                    "message": str(error),
                }
            if child is not None:
                try:
                    os.write(write_fd, b"release\n")
                except OSError:
                    pass
                cleanup_result = cleanup(unit, child, path, shutdown_timeout)
            if whole_guard is not None:
                try:
                    whole_guard_evidence = whole_guard.finish(output)
                    if whole_guard.triggered.is_set() and failure is None:
                        failure = {
                            "type": "WholeCommandGlobalGuardExceeded",
                            "message": "Whole-command global resource guard triggered",
                        }
                except Exception as error:  # noqa: BLE001 - cleanup already completed
                    failure = failure or {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                try:
                    if scope_end_evidence is not None:
                        durable_json(output / "scope-end.json", scope_end_evidence)
                    with (output / "cgroup-samples.jsonl").open("x") as telemetry:
                        for sample in buffered_cgroup_samples:
                            telemetry.write(json.dumps(sample) + "\n")
                        telemetry.flush()
                        os.fsync(telemetry.fileno())
                except Exception as error:  # noqa: BLE001 - owned cleanup finished
                    failure = failure or {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
            for descriptor in (read_fd, write_fd):
                if descriptor >= 0:
                    os.close(descriptor)
            durable_json(output / "cleanup.json", cleanup_result)
    evidence = oom_evidence(samples, after)
    good = (
        failure is None
        and outcome is not None
        and outcome["returncode"] == 0
        and not outcome["timed_out"]
        and not evidence["oom_observed"]
        and cleanup_result["verified"]
    )
    result = {
        "passed": good,
        "failure": failure,
        "command_result": outcome,
        "resource_evidence": evidence,
        "cleanup": cleanup_result,
        "final_cgroup_read_complete": bool(samples and not samples[-1]["errors"]),
    }
    if whole_guard is not None:
        result["whole_command_global_guard"] = whole_guard_evidence
    durable_json(output / "result.json", result)
    if good:
        return 0
    if not cleanup_result["verified"]:
        return 125
    if failure and "signal" in failure:
        return 128 + failure["signal"]
    if outcome and outcome["timed_out"]:
        return 124
    if evidence["oom_observed"]:
        return 137
    if outcome and outcome["returncode"]:
        return (
            outcome["returncode"]
            if outcome["returncode"] > 0
            else 128 - outcome["returncode"]
        )
    return 1


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Value must be finite and positive")
    return number


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--inside":
        return inside(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-max-gib", type=positive, default=140)
    parser.add_argument("--minimum-available-gib", type=positive, default=160)
    parser.add_argument("--command-timeout", type=positive, default=3600)
    parser.add_argument("--shutdown-timeout", type=positive, default=45)
    parser.add_argument("--sample-interval", type=positive, default=1)
    parser.add_argument(
        "--require-inherited-gpu-lock",
        action="store_true",
        help="Required for production nesting inside GPU lifecycle wrappers",
    )
    parser.add_argument(
        "--whole-command-global-guard",
        action="store_true",
        help=(
            "Opt in to outer 1s host sampling across the entire command: "
            "16GiB MemAvailable floor, 256MiB cumulative global swap-out, "
            "0.2 full PSI for three consecutive samples; system-wide attribution"
        ),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A command after -- is required")
    if os.geteuid() == 0:
        parser.error("Use the ordinary user manager, not root")
    output = args.output.resolve()
    if not output.is_relative_to(BULK.resolve()) or output == BULK.resolve():
        parser.error(
            "Output must be a fresh directory under /bulk/dlk/big-local-models"
        )
    output.mkdir(parents=True, exist_ok=False)
    for sig in SIGNALS:
        signal.signal(
            sig, lambda number, frame: (_ for _ in ()).throw(Cancelled(number))
        )
    lock_fd = None
    try:
        lock_fd = inherited_lock()
        if args.require_inherited_gpu_lock and lock_fd is None:
            raise RuntimeError(
                "Production launch requires an inherited GPU lock from the outer lifecycle owner"
            )
        return supervise(
            output,
            command,
            int(args.memory_max_gib * 2**30),
            args.command_timeout,
            args.shutdown_timeout,
            args.sample_interval,
            int(args.minimum_available_gib * 2**30),
            lock_fd,
            whole_command_global_guard=args.whole_command_global_guard,
        )
    except Exception as error:  # noqa: BLE001 - evidence errors must not skip cleanup
        durable_json(
            output / "startup-error.json",
            {"type": type(error).__name__, "message": str(error)},
        )
        print(f"Memory scope failed: {error}", file=sys.stderr)
        return 1
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
