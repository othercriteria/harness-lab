#!/usr/bin/env python3
"""Run one command with idle Ollama models released, then restore their residency.

Usage: with_ollama_released.py --output BULK/FRESH_DIR -- COMMAND [ARG ...]

The original remaining keep-alive duration is replayed after restoration, pausing
its expiry across the command. Residency, digest and context are restored; KV
cache, GPU placement and session-internal state cannot be reconstructed by this
API. No services are stopped. Existing TCP connections cause refusal, including
idle keep-alive connections. Checks cannot prevent a new client racing the next
API call; use a coordinated quiet interval. Before each restoration POST, a fresh
connection snapshot must confirm idleness. A shared idle-wait budget of at most
60 seconds covers restoration checks; busy or ambiguous inspection defers all
remaining POSTs to the saved recovery plan. A new connection can still race the
last check and POST. Extra models are never explicitly unloaded, but Ollama's
scheduler may evict models under memory pressure.

All HTTP calls have total deadlines and bypass proxies/redirects. On cancellation
by SIGINT, SIGTERM or SIGHUP (including terminal/tmux teardown),
the owned child gets SIGTERM and a grace period for its cleanup before Ollama is
restored. Remaining processes in its session's original process group are killed;
commands that daemonize into another session are outside this guarantee. SIGKILL,
host failure and an unavailable Ollama can prevent automatic restoration; durable
payloads and concrete recovery commands are saved before the first unload.
If an owned process cannot be stopped, restoration is reported as blocked instead
of loading Ollama into an overlapping GPU experiment.

API references: https://docs.ollama.com/api/ps and
https://docs.ollama.com/api/generate . An empty prompt loads without generation.
"""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import math
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ORIGIN = "http://127.0.0.1:11434"
BULK = Path("/bulk/dlk/local-harness")
CANCELLATION_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
RESTORATION_IDLE_WAIT_SECONDS = 60
RESTORATION_CONNECTION_TIMEOUT_SECONDS = 5
WRAPPER_PATH = Path(__file__).resolve()
# Capture at startup, rather than rereading a possibly edited file after a run.
WRAPPER_SOURCE = WRAPPER_PATH.read_bytes()


class Cancelled(Exception):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"Received signal {signum}")


class OwnedCleanupFailed(RuntimeError):
    pass


class RestorationDeferred(RuntimeError):
    """No restoration mutation is safe without a fresh successful idle check."""


@contextlib.contextmanager
def ignore_cancellation():
    previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in CANCELLATION_SIGNALS}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


@contextlib.contextmanager
def defer_cancellation():
    pending = []

    def remember(signum, frame):
        pending.append(signum)

    previous = {sig: signal.signal(sig, remember) for sig in CANCELLATION_SIGNALS}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if pending:
            raise Cancelled(pending[0])


@contextlib.contextmanager
def deadline(seconds):
    def expired(signum, frame):
        raise TimeoutError(f"Whole HTTP request exceeded {seconds:g} seconds")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError(f"Ollama redirected a local request ({code})")


def http_json(endpoint, payload=None, timeout=180):
    if endpoint not in {"/api/ps", "/api/show", "/api/tags", "/api/generate"}:
        raise ValueError("Unexpected Ollama endpoint")
    request = urllib.request.Request(
        ORIGIN + endpoint,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Connection": "close"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with deadline(timeout), opener.open(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError(f"Ollama {endpoint} failed: {result}")
    return result


def durable_json(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def snapshot_source(output):
    """Durably retain the startup source and its digest before any API mutation."""
    with (output / "wrapper-source.py").open("xb") as stream:
        stream.write(WRAPPER_SOURCE)
        stream.flush()
        os.fsync(stream.fileno())
    provenance = {
        "original_path": str(WRAPPER_PATH),
        "snapshot_path": "wrapper-source.py",
        "sha256": hashlib.sha256(WRAPPER_SOURCE).hexdigest(),
        "python": sys.version,
        "argv": sys.argv,
        "pid": os.getpid(),
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    # This also fsyncs the directory containing both files.
    durable_json(output / "wrapper-source.json", provenance)
    return provenance["sha256"]


def require_delegation_closed(jobs=BULK / "delegation/jobs"):
    """A released OS lock is not evidence that an interrupted job cleaned up."""
    if not jobs.exists():
        return
    for job in jobs.iterdir():
        if job.is_symlink() or not job.is_dir():
            raise RuntimeError("Unexpected entry in delegated job registry")
        path = job / "state.json"
        if path.is_symlink():
            raise RuntimeError("Delegated state alias rejected")
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise RuntimeError("Delegated state exceeds bound")
        state = json.loads(data)
        if (
            state.get("state") not in {"completed", "failed", "cancelled", "timed_out"}
            or state.get("cleanup_verified") is not True
        ):
            raise RuntimeError(f"Unclosed delegated job requires recovery: {job.name}")


@contextlib.contextmanager
def gpu_experiment_lock(
    root=Path("/bulk/dlk/big-local-models"), *, recovering_delegation=False
):
    """Acquire the canonical lock, or duplicate a validated inherited descriptor.

    Duplicates share the parent's open file description. Close them on exit;
    an explicit LOCK_UN would prematurely unlock the entire nested transaction.
    """
    path = root / "gpu-experiment.lock"
    inherited = os.environ.get("BIG_MODELS_GPU_LOCK_FD")
    if inherited is None:
        lock = path.open("a")
    else:
        try:
            descriptor = int(inherited)
            actual, expected = os.fstat(descriptor), path.stat()
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise ValueError("Inherited descriptor identifies a different file")
            lock = os.fdopen(os.dup(descriptor), "a")
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Invalid inherited GPU lock: {error}") from error
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if inherited is None and not recovering_delegation:
            require_delegation_closed()
        yield lock


def checked_command(argv, timeout=15):
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    record = {
        "argv": argv,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode:
        raise RuntimeError(f"Inspection failed: {record}")
    return record


def service_state():
    state = checked_command(
        [
            "systemctl",
            "show",
            "ollama.service",
            "--no-pager",
            "--property=ActiveState,SubState,MainPID,UnitFileState,InvocationID",
        ]
    )
    state["properties"] = dict(
        line.split("=", 1) for line in state["stdout"].splitlines() if "=" in line
    )
    return state


def connections(timeout=15):
    return checked_command(
        [
            "ss",
            "-Htn",
            "state",
            "established",
            "( sport = :11434 or dport = :11434 )",
        ],
        timeout=timeout,
    )


def wait_for_restoration_idle(save, label, wait_seconds):
    """Durably confirm idle immediately before a POST; never interrupt a client.

    The caller shares the budget across models, excluding model-load API time.
    This is a check, not exclusion: a new connection may race the following POST.
    """
    start = time.monotonic()
    attempt = 0
    while True:
        remaining = wait_seconds - (time.monotonic() - start)
        if remaining <= 0:
            raise RestorationDeferred("Ollama restoration idle-wait budget expired")
        attempt += 1
        timeout = min(RESTORATION_CONNECTION_TIMEOUT_SECONDS, remaining)
        try:
            scan = connections(timeout=timeout)
        except Exception as error:  # noqa: BLE001 - Any inspection loss must block mutation.
            scan = {"error": {"type": type(error).__name__, "message": str(error)}}
        try:
            save(
                f"{label}-{attempt:03d}",
                {
                    "at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "inspection": scan,
                    "inspection_timeout_seconds": timeout,
                    "elapsed_seconds": time.monotonic() - start,
                },
            )
        except Exception as error:
            raise RestorationDeferred(
                f"Could not retain restoration connection snapshot: {error}"
            ) from error
        if (
            not isinstance(scan, dict)
            or type(scan.get("returncode")) is not int
            or scan["returncode"] != 0
            or not isinstance(scan.get("stdout"), str)
            or not isinstance(scan.get("stderr"), str)
            or scan["stderr"].strip()
        ):
            raise RestorationDeferred(
                "Ollama restoration connection inspection failed or was malformed"
            )
        elapsed = time.monotonic() - start
        if elapsed >= wait_seconds:
            raise RestorationDeferred("Ollama restoration idle-wait budget expired")
        if not scan["stdout"].strip():
            return elapsed
        time.sleep(min(1, wait_seconds - elapsed))


def model_name(model):
    return model.get("name") or model["model"]


def identities(ps):
    return sorted(
        (model_name(model), model["digest"], model["context_length"])
        for model in ps["models"]
    )


def make_plan(ps, now):
    plans = []
    seen = set()
    for model in ps["models"]:
        name = model_name(model)
        context = model.get("context_length")
        if (
            not name
            or name in seen
            or not model.get("digest")
            or type(context) is not int
            or context <= 0
        ):
            raise ValueError(
                "Loaded models need unique names, digests and positive context_length"
            )
        seen.add(name)
        expiry = datetime.datetime.fromisoformat(
            model["expires_at"].replace("Z", "+00:00")
        )
        remaining = expiry - now
        remaining_ns = (
            (remaining.days * 86400 + remaining.seconds) * 1_000_000
            + remaining.microseconds
        ) * 1000
        if not 0 < remaining_ns <= 2**63 - 1:
            raise ValueError(
                f"Cannot replay expired or unrepresentable keep-alive for {name}"
            )
        plans.append(
            {
                "name": name,
                "digest": model["digest"],
                "context_length": context,
                "original_expires_at": model["expires_at"],
                "remaining_seconds_at_snapshot": remaining_ns / 1e9,
                "unload": {
                    "model": name,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": 0,
                },
                "restore": {
                    "model": name,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": f"{remaining_ns}ns",
                    "options": {"num_ctx": context},
                },
            }
        )
    return plans


def check_tag(plan, tags):
    matches = [item for item in tags["models"] if model_name(item) == plan["name"]]
    if len(matches) != 1 or matches[0]["digest"] != plan["digest"]:
        raise RuntimeError(
            f"Local tag no longer identifies original digest: {plan['name']}"
        )


def stop_owned(child, shutdown_timeout):
    """Give the direct child its cleanup grace before removing group leftovers."""
    with ignore_cancellation():
        try:
            if child.poll() is None:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=shutdown_timeout)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=10)
            # The direct child has exited; no model server may remain in its group.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            end = time.monotonic() + 10
            while live_group_members(child.pid):
                if time.monotonic() >= end:
                    raise OwnedCleanupFailed(
                        "Owned process group still has live members"
                    )
                time.sleep(0.1)
        except (OSError, subprocess.SubprocessError) as error:
            raise OwnedCleanupFailed(
                f"Could not stop owned command: {error}"
            ) from error


def live_group_members(group):
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            if int(fields[2]) == group and fields[0] not in {"Z", "X"}:
                members.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return members


def run_owned(
    command,
    output,
    command_timeout,
    shutdown_timeout,
    gpu_lock_fd=None,
    *,
    deferred=None,
    on_ready=None,
):
    child = None
    environment = os.environ.copy()
    # An inherited lock is only valid when it is the descriptor owned here.
    environment.pop("BIG_MODELS_GPU_LOCK_FD", None)
    pass_fds = ()
    if deferred is not None:
        environment["BIG_MODELS_DEFERRED_DIR"] = str(deferred["dir"])
        environment["BIG_MODELS_DEFERRED_NONCE"] = deferred["nonce"]
    else:
        environment.pop("BIG_MODELS_DEFERRED_DIR", None)
        environment.pop("BIG_MODELS_DEFERRED_NONCE", None)
    if gpu_lock_fd is not None:
        environment["BIG_MODELS_GPU_LOCK_FD"] = str(gpu_lock_fd)
        pass_fds = (gpu_lock_fd,)
    with (output / "command.log").open("x") as log:
        try:
            # Assign the child handle before a pending cancellation is delivered.
            with defer_cancellation():
                child = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    pass_fds=pass_fds,
                    env=environment,
                )
                durable_json(output / "child.json", {"pid": child.pid, "argv": command})
            started = time.monotonic()
            if deferred is not None:
                ready_path = deferred["dir"] / "ready.json"
                ready_deadline = started + min(
                    deferred["ready_timeout"], command_timeout
                )
                while not ready_path.exists():
                    if child.poll() is not None:
                        raise RuntimeError(
                            "Owned command exited before verification readiness"
                        )
                    if time.monotonic() >= ready_deadline:
                        raise TimeoutError(
                            "Timed out waiting for verification readiness"
                        )
                    time.sleep(0.1)
                ready = json.loads(ready_path.read_bytes())
                if (
                    not isinstance(ready, dict)
                    or set(ready) != {"event", "nonce", "receipt_sha256", "runner_pid"}
                    or ready["event"] != "receipt-verified"
                    or ready["nonce"] != deferred["nonce"]
                    or not isinstance(ready["receipt_sha256"], str)
                    or len(ready["receipt_sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in ready["receipt_sha256"])
                    or type(ready["runner_pid"]) is not int
                    or ready["runner_pid"] <= 0
                ):
                    raise ValueError("Invalid verification readiness record")
                durable_json(output / "deferred-ready.json", ready)
                on_ready(child)
                if child.poll() is not None:
                    raise RuntimeError(
                        "Owned command exited before release acknowledgement"
                    )
                tmp = deferred["dir"] / "ack.tmp"
                durable_json(
                    tmp, {"event": "ollama-released", "nonce": deferred["nonce"]}
                )
                os.replace(tmp, deferred["dir"] / "ack.json")
                deferred["completed"] = True
            timeout = (
                command_timeout
                if deferred is None
                else max(0, command_timeout - (time.monotonic() - started))
            )
            return child.wait(timeout=timeout)
        finally:
            if child is not None:
                stop_owned(child, shutdown_timeout)


def execute(
    command,
    output,
    api_timeout=180,
    command_timeout=3600,
    shutdown_timeout=90,
    gpu_lock_fd=None,
    deferred_unload=False,
    ready_timeout=3600,
):
    result = {
        "ok": False,
        "command": command,
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "mutation_attempted": False,
        "restoration": [],
        "command_exit_code": None,
    }
    plans = []
    original_service = None
    sequence = 0

    def save(label, data):
        nonlocal sequence
        sequence += 1
        durable_json(output / f"{sequence:03d}-{label}.json", data)

    def api(endpoint, payload=None):
        return http_json(endpoint, payload, timeout=api_timeout)

    def idle(label):
        scan = connections()
        save(label, scan)
        if scan["stdout"].strip():
            raise RuntimeError(
                "Established Ollama connection detected; coordinate a quiet interval before retrying"
            )

    try:
        result["wrapper_source_sha256"] = snapshot_source(output)

        def release_models(child=None):
            nonlocal plans, original_service
            if child is not None and child.poll() is not None:
                raise RuntimeError("Owned command exited before unload preflight")
            original_service = service_state()
            save("service-before", original_service)
            if original_service["properties"].get("ActiveState") != "active":
                raise RuntimeError(
                    "Ollama must already be active; this wrapper does not start or stop services"
                )
            ps = api("/api/ps")
            now = datetime.datetime.now(datetime.UTC)
            save("ps-before", {"snapshot_at": now.isoformat(), "response": ps})
            idle("connections-before")
            plans = make_plan(ps, now)
            tags = api("/api/tags")
            save("tags-before", tags)
            for index, plan in enumerate(plans):
                check_tag(plan, tags)
                save(f"show-{index:03d}", api("/api/show", {"model": plan["name"]}))
                for action in ("unload", "restore"):
                    payload_path = output / f"model-{index:03d}-{action}.json"
                    durable_json(payload_path, plan[action])
                    plan[f"{action}_argv"] = [
                        "curl",
                        "--fail-with-body",
                        "--max-time",
                        str(api_timeout),
                        "--noproxy",
                        "*",
                        "--json",
                        "@" + str(payload_path),
                        ORIGIN + "/api/generate",
                    ]
            durable_json(
                output / "recovery-plan.json",
                {
                    "models": plans,
                    "service": original_service,
                    "expiry_policy": "Replay each model's remaining keep-alive at snapshot after reloading; expiry is shifted, not kept at its old wall-clock deadline.",
                    "limitations": __doc__,
                },
            )
            # Recheck both state and connections after durable recovery instructions exist.
            expected = identities(ps)
            current = api("/api/ps")
            save("ps-pre-unload", current)
            if identities(current) != expected or [
                m["expires_at"] for m in current["models"]
            ] != [m["expires_at"] for m in ps["models"]]:
                raise RuntimeError(
                    "Ollama residency/expiry changed during preflight; retry in a quiet interval"
                )
            idle("connections-pre-unload")
            for index, plan in enumerate(plans):
                if child is not None and child.poll() is not None:
                    raise RuntimeError("Owned command exited before unload")
                current = api("/api/ps")
                save(f"ps-before-unload-{index:03d}", current)
                if identities(current) != expected:
                    raise RuntimeError(
                        "Ollama residency changed before unload; aborting remaining unloads"
                    )
                idle(f"connections-before-unload-{index:03d}")
                result["mutation_attempted"] = (
                    True  # A timed-out POST may have completed server-side.
                )
                save(
                    f"unload-response-{index:03d}", api("/api/generate", plan["unload"])
                )
                expected.remove((plan["name"], plan["digest"], plan["context_length"]))
                current = api("/api/ps")
                save(f"ps-after-unload-{index:03d}", current)
                if identities(current) != expected:
                    raise RuntimeError(
                        "Unload did not produce expected residency; command will not start"
                    )
            idle("connections-before-command")

        inherited_lock = {} if gpu_lock_fd is None else {"gpu_lock_fd": gpu_lock_fd}
        if deferred_unload:
            handshake_dir = output / "deferred-handshake"
            handshake_dir.mkdir(mode=0o700)
            deferred = {
                "dir": handshake_dir,
                "nonce": secrets.token_hex(32),
                "ready_timeout": ready_timeout,
                "completed": False,
            }
            result["command_exit_code"] = run_owned(
                command,
                output,
                command_timeout,
                shutdown_timeout,
                deferred=deferred,
                on_ready=release_models,
                **inherited_lock,
            )
            result["deferred_handshake_completed"] = deferred["completed"]
            if not deferred["completed"]:
                raise RuntimeError("Deferred handshake incomplete")
        else:
            release_models()
            result["command_exit_code"] = run_owned(
                command, output, command_timeout, shutdown_timeout, **inherited_lock
            )
    except BaseException as error:  # noqa: BLE001 - Every failure must reach restoration.
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        if isinstance(error, Cancelled):
            result["cancelled_signal"] = error.signum
        if isinstance(error, OwnedCleanupFailed):
            result["owned_cleanup_failed"] = True
    finally:
        with ignore_cancellation():
            if result.get("owned_cleanup_failed"):
                result["restoration_verified"] = False
                result["restoration_blocked"] = (
                    "Owned command cleanup could not be verified; stop its recorded session before replaying recovery-plan.json."
                )
            elif result["mutation_attempted"]:
                # Attempt originals, including uncertain unloads, until an idle
                # inspection blocks further mutations. API load time does not
                # consume the shared, capped idle-wait budget.
                idle_budget = min(api_timeout, RESTORATION_IDLE_WAIT_SECONDS)
                result["restoration_idle_wait_budget_seconds"] = idle_budget
                for index, plan in enumerate(plans):
                    restoration = {"name": plan["name"], "ok": False}
                    if result.get("restoration_blocked"):
                        restoration["deferred"] = True
                        result["restoration"].append(restoration)
                        continue
                    try:
                        check_tag(plan, api("/api/tags"))
                        waited = wait_for_restoration_idle(
                            save, f"connections-before-restore-{index:03d}", idle_budget
                        )
                        idle_budget = max(0, idle_budget - waited)
                        restoration["idle_check_seconds"] = waited
                        save(
                            f"restore-response-{index:03d}",
                            api("/api/generate", plan["restore"]),
                        )
                        restoration["ok"] = True
                    except RestorationDeferred as error:
                        restoration["deferred"] = True
                        restoration["error"] = {
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                        result["restoration_blocked"] = {
                            "reason": str(error),
                            "recovery_plan": str(output / "recovery-plan.json"),
                            "pending_models": [
                                {
                                    "name": pending["name"],
                                    "restore_argv": pending["restore_argv"],
                                }
                                for pending in plans[index:]
                            ],
                            "instruction": "Coordinate an idle interval, then replay the retained payloads; no further restoration POST was sent.",
                            "residual_race": "A new client may connect between the final idle check and POST; this wrapper does not lock out clients.",
                        }
                        try:
                            save("restoration-deferred", result["restoration_blocked"])
                        except Exception as save_error:  # noqa: BLE001 - Evidence failure must not skip verification.
                            restoration["evidence_error"] = str(save_error)
                    except BaseException as error:  # noqa: BLE001 - Try every original model.
                        restoration["error"] = {
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    result["restoration"].append(restoration)
                try:
                    final_ps = api("/api/ps")
                    save("ps-after-restoration", final_ps)
                    present = identities(final_ps)
                    for restoration, plan in zip(
                        result["restoration"], plans, strict=True
                    ):
                        restoration["verified_digest_and_context"] = (
                            plan["name"],
                            plan["digest"],
                            plan["context_length"],
                        ) in present
                    result["restoration_verified"] = all(
                        item["ok"] and item["verified_digest_and_context"]
                        for item in result["restoration"]
                    )
                    result["extra_loaded_models"] = [
                        item
                        for item in present
                        if item
                        not in [
                            (p["name"], p["digest"], p["context_length"]) for p in plans
                        ]
                    ]
                except BaseException as error:  # noqa: BLE001 - Preserve failed verification.
                    result["restoration_verified"] = False
                    result["verification_error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
            else:
                result["restoration_verified"] = None
            try:
                final_service = service_state()
                save("service-after", final_service)
                result["service_unchanged"] = (
                    original_service is not None
                    and final_service["properties"] == original_service["properties"]
                )
            except BaseException as error:  # noqa: BLE001 - Preserve service inspection failures.
                result["service_unchanged"] = False
                result["service_verification_error"] = str(error)
            result["ok"] = (
                "error" not in result
                and result["command_exit_code"] == 0
                and result["service_unchanged"]
                and (not result["mutation_attempted"] or result["restoration_verified"])
                and not result.get("restoration_blocked")
            )
            result["finished_at"] = datetime.datetime.now(datetime.UTC).isoformat()
            durable_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Fresh evidence directory under project bulk",
    )
    parser.add_argument(
        "--defer-unload-until-verified",
        action="store_true",
        help="Wait for the owned runner to verify its receipt before unloading",
    )
    parser.add_argument("--ready-timeout", type=float, default=3600)
    parser.add_argument("--api-timeout", type=float, default=180)
    parser.add_argument("--command-timeout", type=float, default=3600)
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=90,
        help="Grace for the owned command's cleanup before restoring Ollama",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or any(
        not math.isfinite(value) or value <= 0
        for value in (
            args.api_timeout,
            args.command_timeout,
            args.shutdown_timeout,
            args.ready_timeout,
        )
    ):
        parser.error("Provide a command after -- and positive finite timeouts")
    output = args.output.resolve()
    if not output.is_relative_to(BULK.resolve()):
        parser.error("Evidence must remain under /bulk/dlk/big-local-models")
    output.mkdir(parents=True, exist_ok=False)
    parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    # Keep the GPU transaction locked across unload, command cleanup and restore.
    # The child inherits the same open file description; it must close, not unlock.
    with (
        (BULK / "ollama-release.lock").open("a") as lock,
        gpu_experiment_lock() as gpu_lock,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def cancelled(signum, frame):
            raise Cancelled(signum)

        previous = {sig: signal.signal(sig, cancelled) for sig in CANCELLATION_SIGNALS}
        try:
            result = execute(
                command,
                output,
                args.api_timeout,
                args.command_timeout,
                args.shutdown_timeout,
                gpu_lock_fd=gpu_lock.fileno(),
                deferred_unload=args.defer_unload_until_verified,
                ready_timeout=args.ready_timeout,
            )
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    print(json.dumps(result), flush=True)
    if result.get("cancelled_signal"):
        return 128 + result["cancelled_signal"]
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
