"""Durable outer-only delegated jobs. No solver gets this control interface."""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path

import with_background_released as background
import with_ollama_released as lifecycle
import with_speech_released as voice
from control import defer_launch_signals
from delegate_artifacts import encoded, export_candidate
from delegate_package import STORE, TASK, package_path, register, sha, verify_package
from server_endpoint import EndpointOwnershipError
from server_endpoint import process_identity as endpoint_process_identity

RUNS = Path("/bulk/dlk/local-harness/runs")
SESSIONS = Path("/bulk/dlk/local-harness/sessions")
TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def process_identity(pid):
    return {**endpoint_process_identity(pid), "boot_id": boot_id()}


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


def read(path, limit=1024 * 1024):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Control file alias rejected")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Control record exceeds bound")
    return json.loads(data)


def atomic(path, value):
    path = Path(path)
    temp = path.with_name(".write-" + uuid.uuid4().hex)
    try:
        with temp.open("xb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def job_path(identifier, store=STORE):
    if not isinstance(identifier, str) or not re.fullmatch("[a-f0-9]{32}", identifier):
        raise ValueError("Invalid job ID")
    path = store / "jobs" / identifier
    if path.is_symlink():
        raise ValueError("Job aliases are forbidden")
    return path


def live(identity):
    return owner_inspection(identity) == "live"


def owner_inspection(identity):
    """Restricted observers cannot infer owner death from inaccessible /proc."""
    if not identity:
        return "absent"
    try:
        if identity.get("boot_id") != boot_id():
            return "absent"
        if identity.get("network_namespace") != os.readlink("/proc/self/ns/net"):
            return "unavailable"
        return "live" if process_identity(identity["pid"]) == identity else "absent"
    except PermissionError:
        return "unavailable"
    except (FileNotFoundError, EndpointOwnershipError):
        return "absent"
    except (OSError, ValueError, RuntimeError):
        return "unavailable"


def update(job, state, **fields):
    old = read(job / "state.json")
    record = {**old, **fields, "state": state, "updated_at": now()}
    # Single worker writer; cancellation has its own independent request file.
    sequence = len(list((job / "events").glob("*.json")))
    event = {"sequence": sequence, "at": record["updated_at"], "state": state, **fields}
    target = job / "events" / f"{sequence:05d}.json"
    if target.exists():
        raise RuntimeError("Event collision; recovery required")
    atomic(target, event)
    atomic(job / "state.json", record)
    return record


def status(identifier, store=STORE):
    job = job_path(identifier, store)
    record = read(job / "state.json")
    record["cancel_requested"] = (job / "cancel.json").exists()
    if (job / "review.json").exists():
        review = read(job / "review.json")
        if review.get("job_id") == identifier and review.get(
            "package_id"
        ) == record.get("package_id"):
            record["acceptance"] = review.get("decision", "pending")
    if (job / "application.json").exists():
        application = read(job / "application.json")
        record["application_state"] = application.get("state")
        record["applied"] = application.get("applied") is True
    inspection = owner_inspection(record.get("owner"))
    record["owner_inspection"] = inspection
    if record["state"] not in TERMINAL and inspection == "absent":
        record["recorded_state"] = record["state"]
        record["state"] = "recovery_required"
        record["reason"] = "Owner absent; cleanup must be reconciled before admission"
    return record


def validate_request(request, store=STORE):
    if not isinstance(request, dict) or set(request) - {"classification"} != {
        "package_id",
        "idempotency_key",
        "session_id",
        "seed",
        "total_seconds",
    }:
        raise ValueError("Invalid delegated request")
    if "classification" in request and request["classification"] not in (
        "diagnostic_replay",
        "lifecycle_acceptance",
        "useful_work",
    ):
        raise ValueError("Unknown delegated job classification")
    package_path(request["package_id"], store)
    if not isinstance(request["idempotency_key"], str) or not re.fullmatch(
        r"[a-zA-Z0-9_.:/-]{1,160}", request["idempotency_key"]
    ):
        raise ValueError("Invalid idempotency key")
    if not isinstance(request["session_id"], str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}-gpu-quiet-\d{3}", request["session_id"]
    ):
        raise ValueError("Expected an explicit recorded work session")
    if type(request["seed"]) is not int or not 0 <= request["seed"] <= 2**31 - 1:
        raise ValueError("Invalid seed")
    if (
        type(request["total_seconds"]) is not int
        or not 30 <= request["total_seconds"] <= 2400
    ):
        raise ValueError("Invalid dispatch deadline")


def require_quiet_session(identifier):
    session = SESSIONS / identifier
    if session.is_symlink() or (session / "restoration-verification.json").exists():
        raise RuntimeError("Session is restored or aliased")
    if read(session / "active.json")["status"] != "quiet":
        raise RuntimeError("Requires an explicitly gated active work session")
    plan = session / "restoration-plan.json"
    read(plan)
    if any(row["ActiveState"] != "inactive" for row in background.state().values()):
        raise RuntimeError("Background workloads are not session-gated")
    for unit in (voice.TARGET, *voice.UNITS):
        if voice.systemctl("show", unit)["properties"]["ActiveState"] != "inactive":
            raise RuntimeError("Voice workloads are not session-gated")
    return {"path": str(plan), "sha256": sha(plan)}


def require_no_unclosed_jobs(store):
    for path in sorted((store / "jobs").glob("*/state.json")):
        record = read(path)
        if record["state"] not in TERMINAL or not record.get("cleanup_verified"):
            raise RuntimeError(
                f"Unclosed delegated job requires recovery: {path.parent.name}"
            )


def submit(request, store=STORE):
    submitted = time.monotonic()
    submitted_at = now()
    validate_request(request, store)
    if store != STORE:
        raise ValueError("Detached submission requires the production store")
    if os.environ.get("BIG_MODELS_GPU_LOCK_FD"):
        raise RuntimeError("Submission cannot borrow another operation's GPU lease")
    store.mkdir(parents=True, exist_ok=True)
    (store / "jobs").mkdir(exist_ok=True)
    (store / "keys").mkdir(exist_ok=True)
    key = hashlib.sha256(request["idempotency_key"].encode()).hexdigest()
    request_hash = hashlib.sha256(encoded(request)).hexdigest()
    with (store / "admission.lock").open("a") as admission:
        fcntl.flock(admission, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = store / "keys" / (key + ".json")
        if previous.exists():
            record = read(previous)
            if record["request_sha256"] != request_hash:
                raise ValueError("Idempotency key conflicts with another request")
            return status(record["job_id"], store)
        # Fail before package preparation, accepted-job creation or service changes.
        with lifecycle.gpu_experiment_lock() as gpu:
            require_no_unclosed_jobs(store)
            package, config = verify_package(request["package_id"], store)
            restoration = require_quiet_session(request["session_id"])
            identifier = uuid.uuid4().hex
            job = job_path(identifier, store)
            job.mkdir()
            (job / "events").mkdir()
            owner = process_identity(os.getpid())
            atomic(job / "request.json", request)
            if "classification" in request:
                atomic(
                    job / "classification.json",
                    {
                        "job_id": identifier,
                        "kind": request["classification"],
                        "source": "dispatch",
                    },
                )
            atomic(
                job / "state.json",
                {
                    "job_id": identifier,
                    "label": config["label"],
                    "state": "accepted",
                    "owner": owner,
                    "owner_role": "submitter",
                    "submitted_at": submitted_at,
                    "submitted_monotonic": submitted,
                    "submitted_boot_id": boot_id(),
                    "request_sha256": request_hash,
                    "package_id": request["package_id"],
                    "snapshot_id": config["snapshot_id"],
                    "run": str(RUNS / ("delegate-" + identifier)),
                    "session_restoration": restoration,
                    "cleanup_verified": False,
                    "acceptance": "pending",
                    "applied": False,
                },
            )
            atomic(previous, {"job_id": identifier, "request_sha256": request_hash})
            command = [
                str(package / "runtime/.venv/bin/python"),
                str(package / "runtime/scripts/delegate_job.py"),
                "_worker",
                identifier,
            ]
            environment = os.environ | {"BIG_MODELS_GPU_LOCK_FD": str(gpu.fileno())}
            # Production store is fixed; only direct test helpers accept substitutes.
            with (job / "worker.log").open("xb") as log:
                with defer_launch_signals():
                    subprocess.Popen(
                        command,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        start_new_session=True,
                        env=environment,
                        pass_fds=(gpu.fileno(),),
                    )
            return {
                "job_id": identifier,
                "state": "accepted",
                "request_sha256": request_hash,
            }


def cancel(identifier, reason, store=STORE):
    if not isinstance(reason, str) or not 1 <= len(reason.encode()) <= 1000:
        raise ValueError("Provide a bounded cancellation reason")
    job = job_path(identifier, store)
    record = status(identifier, store)
    if record["state"] in TERMINAL:
        return record
    if not (job / "cancel.json").exists():
        atomic(job / "cancel.json", {"requested_at": now(), "reason": reason})
    # Never signal the submitter, a reused PID, or an owner that has disappeared.
    identity = record.get("owner")
    if record.get("owner_role") == "worker" and live(identity):
        try:
            fd = os.pidfd_open(identity["pid"])
            try:
                if not live(identity):
                    raise RuntimeError("Worker identity changed before cancellation")
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        except ProcessLookupError:
            pass
    return {
        **record,
        "cancel_requested": True,
        "note": "Request recorded; cancellation is not cleanup completion",
    }


def closure(run):
    """Require positive outer receipts, including partial/failed/cancelled jobs."""
    bg = read(run / "background/summary.json")
    vo = read(run / "voice/result.json")
    ol = read(run / "ollama/result.json")
    mem = read(run / "memory/cleanup.json")
    if not (
        bg.get("restored")
        and vo.get("states_verified")
        and mem.get("verified")
        and (
            ol.get("restoration_verified")
            or (ol.get("service_unchanged") and not ol.get("mutation_attempted"))
        )
    ):
        raise RuntimeError("Incomplete lifecycle closure")
    experiment = run / "experiment/summary.json"
    if (run / "experiment").exists():
        summary = read(experiment)
        if not summary.get("server_stopped") or not summary.get("client_stopped"):
            raise RuntimeError("Owned server/client closure unverified")
    invocations = list((run / "experiment").rglob("*.invocation.json"))
    receipts = list((run / "experiment").rglob("*.cleanup.json"))
    for invocation in invocations:
        cleanup_path = invocation.with_name(
            invocation.name.removesuffix(".invocation.json") + ".cleanup.json"
        )
        request, cleanup = read(invocation), read(cleanup_path)
        if (
            cleanup.get("unit") != request.get("unit")
            or cleanup.get("verified") is not True
            or cleanup.get("owned_process_reaped") is not True
        ):
            raise RuntimeError("Candidate/evaluator cleanup unverified")
    if not all(read(p).get("verified") is True for p in receipts):
        raise RuntimeError("Candidate/evaluator cleanup unverified")
    trials = list((run / "experiment").glob("trial-*"))
    missing_summaries = []
    for trial in trials:
        if not (trial / "summary.json").exists():
            # Cancellation can stop the client before it journals its result.
            # All independent sandbox invocations above still need receipts;
            # the model/client additionally need positive whole-scope closure.
            if mem.get("cgroup_empty_or_absent") is not True:
                raise RuntimeError("Missing trial result without whole-scope closure")
            missing_summaries.append(str(trial))
            continue
        summary = read(trial / "summary.json", limit=16 * 1024 * 1024)
        if summary.get("unsafe_cleanup"):
            raise RuntimeError("Trial reported unsafe cleanup")
    paths = [
        run / p
        for p in (
            "background/summary.json",
            "voice/result.json",
            "ollama/result.json",
            "memory/cleanup.json",
        )
    ]
    if experiment.exists():
        paths.append(experiment)
    return {
        "verified": True,
        "missing_trial_summaries": missing_summaries,
        "trial_results_complete": not missing_summaries,
        "receipts": {
            str(p): sha(p)
            for p in [
                *paths,
                *invocations,
                *receipts,
                *(t / "summary.json" for t in trials if (t / "summary.json").exists()),
            ]
        },
    }


def collect(job, package, run):
    trial = run / "experiment" / ("trial-00-" + TASK)
    summary_path = trial / "summary.json"
    if not summary_path.exists():
        return {
            "disposition": "no_submission",
            "trial": None,
            "acceptance": "pending",
            "error": "No terminal trial summary; inspect lifecycle logs",
        }
    # Full trace/check transport belongs in the outer artifact, not CLI results.
    summary = read(summary_path, limit=16 * 1024 * 1024)
    workspace = Path(summary["final_workspace"])
    if workspace.is_symlink() or not workspace.resolve().is_relative_to(
        trial / "workspaces"
    ):
        raise ValueError("Candidate workspace does not belong to job")
    brief = (package / "runtime/tasks" / TASK / "public/task.md").read_bytes()
    artifact = export_candidate(
        package / "source", workspace, job / "artifact", brief=brief
    )
    verification = summary.get("verification", {})
    if (
        verification.get("artifact_sha256")
        != hashlib.sha256(encoded(artifact)).hexdigest()
    ):
        raise ValueError("Check evidence is missing or describes a different artifact")
    return {
        "disposition": summary.get("agent_outcome", {}).get(
            "exit_status", "no_submission"
        ),
        "trial": str(trial),
        "summary_sha256": sha(summary_path),
        "artifact": {
            "manifest": str(job / "artifact/artifact.json"),
            "manifest_sha256": sha(job / "artifact/artifact.json"),
            "changed_files": len(artifact["changes"]),
            "diff": str(job / "artifact/changes.diff"),
            "diff_sha256": artifact["diff_sha256"],
        },
        "acceptance": "pending",
        "applied": False,
        "checks_passed": summary.get("independent_checks_passed"),
        "clean_agent_completion": summary.get("clean_agent_completion"),
        "within_task_budget": summary.get("within_budget"),
        "worker_task_seconds": summary.get("task_wall_seconds"),
        "qualification": "Model completion and check outcomes require independent outer review",
    }


def execute_owned(
    job, command, timeout, gpu_fd, close, collect_result, shutdown_seconds=90
):
    """Control core, exercised with harmless CPU commands before real inference."""
    prior = read(job / "state.json")
    started = prior["submitted_monotonic"]
    state, error, result = "completed", None, None
    child_started = False
    owned_cleanup_failed = False

    def interrupted(signum, frame):
        raise lifecycle.Cancelled(signum)

    previous = {
        s: signal.signal(s, interrupted) for s in lifecycle.CANCELLATION_SIGNALS
    }
    try:
        update(
            job, "preparing", owner=process_identity(os.getpid()), owner_role="worker"
        )
        if (job / "cancel.json").exists():
            state = "cancelled"
        else:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                state = "timed_out"
            else:
                update(job, "running")
                atomic(job / "launch-intent.json", {"at": now(), "command": command})
                child_started = True
                rc = lifecycle.run_owned(
                    command, job, remaining, shutdown_seconds, gpu_lock_fd=gpu_fd
                )
                if rc != 0:
                    state = "failed"
    except lifecycle.Cancelled as exc:
        state, error = "cancelled", str(exc)
    except subprocess.TimeoutExpired:
        state, error = "timed_out", "Total dispatch deadline reached"
    except BaseException as exc:
        state, error = "failed", f"{type(exc).__name__}: {exc}"
        owned_cleanup_failed = isinstance(exc, lifecycle.OwnedCleanupFailed)
    finally:
        with lifecycle.ignore_cancellation():
            update(job, "cleaning", error=error)
            try:
                evidence = (
                    close()
                    if child_started
                    else {"verified": True, "not_launched": True}
                )
                if owned_cleanup_failed or evidence.get("verified") is not True:
                    raise RuntimeError("Owned command cleanup remains unverified")
                atomic(job / "closure.json", evidence)
                if child_started:
                    try:
                        result = collect_result()
                    except Exception as exc:
                        error = (
                            f"Artifact collection failed: {type(exc).__name__}: {exc}"
                        )
                        if state == "completed":
                            state = "failed"
                atomic(
                    job / "result.json",
                    {
                        "result": result,
                        "error": error,
                        "acceptance": "pending",
                        "applied": False,
                        "dispatch_seconds": time.monotonic() - started,
                        "execution_state": state,
                        "cleanup_verified": True,
                    },
                )
                update(
                    job,
                    state,
                    cleanup_verified=True,
                    error=error,
                    completed_at=now(),
                    dispatch_seconds=time.monotonic() - started,
                )
            except BaseException as exc:
                update(
                    job,
                    "recovery_required",
                    cleanup_verified=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
    return read(job / "state.json")


def worker(identifier, store=STORE):
    job = job_path(identifier, store)
    request = read(job / "request.json")
    validate_request(request, store)
    if read(job / "state.json").get("submitted_boot_id") != boot_id():
        raise RuntimeError(
            "Job belongs to a previous boot; recover instead of restarting"
        )
    # This descriptor must have been deliberately inherited from submit.
    if not os.environ.get("BIG_MODELS_GPU_LOCK_FD"):
        raise RuntimeError("Worker requires the submission lease")
    with lifecycle.gpu_experiment_lock() as gpu:
        package, config = verify_package(request["package_id"], store)
        if (
            hashlib.sha256(encoded(request)).hexdigest()
            != read(job / "state.json")["request_sha256"]
        ):
            raise ValueError("Job request changed after admission")
        require_quiet_session(request["session_id"])
        runtime = package / "runtime"
        run = RUNS / ("delegate-" + identifier)
        command = [
            str(runtime / ".venv/bin/python"),
            str(runtime / "scripts/launch_pilot.py"),
            "--profile",
            config["profile"],
            "--protocol",
            config["protocol"],
            "--tasks",
            TASK,
            "--split",
            "development",
            "--seeds",
            str(request["seed"]),
            "--weight-verification",
            "metadata",
            "--output",
            str(run),
        ]
        return execute_owned(
            job,
            command,
            request["total_seconds"],
            gpu.fileno(),
            lambda: closure(run),
            lambda: collect(job, package, run),
        )


def recover(identifier, store=STORE):
    """Outer reconciliation only; never kill an unknown owner or presume cleanup."""
    job = job_path(identifier, store)
    record = status(identifier, store)
    if record["state"] in TERMINAL:
        return record
    if owner_inspection(record.get("owner")) != "absent":
        raise RuntimeError(
            "Owner still live or inspection unavailable; use host inspection, cancel and wait"
        )
    if os.environ.get("BIG_MODELS_GPU_LOCK_FD"):
        raise RuntimeError("Recovery cannot borrow another lease")
    with lifecycle.gpu_experiment_lock(recovering_delegation=True):
        if (job / "launch-intent.json").exists():
            evidence = closure(Path(record["run"]))
        else:
            evidence = {"verified": True, "not_launched": True}
        atomic(job / "closure.json", evidence)
        terminal = "cancelled" if (job / "cancel.json").exists() else "failed"
        prior = {}
        if (job / "result.json").exists():
            prior = read(job / "result.json")
            archive = job / "pre-recovery-result.json"
            if not archive.exists():
                atomic(archive, prior)
        atomic(
            job / "result.json",
            {
                **prior,
                "execution_state": terminal,
                "acceptance": "pending",
                "applied": False,
                "cleanup_verified": True,
                "error": "Worker interrupted; closure reconciled, raw traces preserved",
                "pre_recovery_result": str(job / "pre-recovery-result.json")
                if prior
                else None,
            },
        )
        return update(
            job,
            terminal,
            cleanup_verified=True,
            error="Interrupted owner; cleanup subsequently reconciled",
            recovered_at=now(),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "register",
            "submit",
            "status",
            "result",
            "cancel",
            "recover",
            "_worker",
        ],
    )
    parser.add_argument("value")
    parser.add_argument("--reason", default="Outer caller requested cancellation")
    args = parser.parse_args()
    if args.operation == "register":
        result = register(read(Path(args.value)))
    elif args.operation == "submit":
        result = submit(read(Path(args.value)))
    elif args.operation == "status":
        result = status(args.value)
    elif args.operation == "cancel":
        result = cancel(args.value, args.reason)
    elif args.operation == "recover":
        result = recover(args.value)
    elif args.operation == "_worker":
        result = worker(args.value)
    else:
        record = status(args.value)
        result_path = job_path(args.value) / "result.json"
        result = {
            "status": record,
            "result": read(result_path) if result_path.exists() else None,
            "result_provisional": result_path.exists()
            and record["state"] not in TERMINAL,
        }
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
