"""Isolated command transport adapted from the sibling experiment.

See configs/reused-sources.json for provenance. No model or GPU lifecycle here.
"""

import contextlib
import copy
import hashlib
import json
import math
import os
import re
import selectors
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path

from call_budget import MAX_CALLS, MAX_OBSERVATION_BYTES
from control import UnsafeCleanup, defer_launch_signals
from fresh_context import validate_history_archive

WORKER = Path(__file__).with_name("sandbox_worker.py").resolve()
WORK_BYTES = 16 * 1024 * 1024
MAX_FILES = 2048


def validate_observation_archive(observations, prefix):
    archive = Path(observations)
    expected = prefix.parent / "observations"
    if archive.is_symlink() or archive.resolve() != expected.resolve():
        raise ValueError("Observation mount must belong to this attempt")
    total = 0
    entries = list(archive.iterdir())
    if len(entries) > 2 * MAX_CALLS + 1:
        raise ValueError("Observation archive entry limit")
    for entry in entries:
        if (
            entry.is_symlink()
            or not entry.is_file()
            or not (
                entry.name == "manifest.json"
                or re.fullmatch(r"o[0-9]{4}\.(txt|json|message\.txt)", entry.name)
            )
        ):
            raise ValueError("Unexpected observation archive entry")
        total += entry.stat().st_size
    if total > MAX_OBSERVATION_BYTES:
        raise ValueError("Observation archive byte limit")
    return archive


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


@contextlib.contextmanager
def protected_cleanup():
    # A repeated TERM/INT is delivered only after owned cleanup/evidence finishes.
    previous = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        {signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM},
    )
    fatal = sys.exception()
    if not isinstance(fatal, UnsafeCleanup):
        fatal = None
    try:
        yield
    except UnsafeCleanup as error:
        fatal = error
        raise
    finally:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        except BaseException as error:
            if fatal is not None:
                fatal.add_note(
                    f"Signal-mask restoration interrupted: {type(error).__name__}"
                )
                raise fatal from error
            raise


def checked_command(argv):
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=15, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"Required command failed: {argv!r}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def tool_path(name):
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Required host tool unavailable: {name}")
    resolved = Path(found).resolve()
    alias = resolved.parent / name
    # Nix/coreutils/systemd may dispatch using argv[0]; retain the alias.
    return str(alias if alias.exists() else Path(found).absolute())


class Runtime:
    def __init__(self, bwrap=None, *, python_test_library=None, library_catalog=None):
        candidates = sorted(Path("/nix/store").glob("*-bubblewrap-0.11.2/bin/bwrap"))
        self.bwrap = (
            str(Path(bwrap).resolve())
            if bwrap
            else shutil.which("bwrap") or (str(candidates[0]) if candidates else None)
        )
        if not self.bwrap:
            raise RuntimeError("bubblewrap unavailable; no unsandboxed fallback")
        self.systemd_run = tool_path("systemd-run")
        self.systemctl = tool_path("systemctl")
        self.python = str(Path(sys.executable).resolve())
        names = (
            "bash",
            "cat",
            "ls",
            "head",
            "tail",
            "cp",
            "mv",
            "rm",
            "mkdir",
            "find",
            "grep",
            "git",
            "sed",
            "diff",
            "cmp",
            "cut",
            "md5sum",
            "mktemp",
            "patch",
            "sort",
            "wc",
            "env",
            "timeout",
            "touch",
            "pwd",
            "true",
        )
        self.tools = {name: tool_path(name) for name in names}
        self.tools.update(
            python3=self.python, python=self.python, sh=self.tools["bash"]
        )
        roots = set()
        for path in self.tools.values():
            parts = Path(path).parts
            if len(parts) < 5 or parts[:3] != ("/", "nix", "store"):
                raise RuntimeError(
                    f"Runtime must come from immutable Nix store: {path}"
                )
            roots.add(str(Path(*parts[:4])))
        closure = checked_command(
            [tool_path("nix-store"), "--query", "--requisites", *sorted(roots)]
        )
        self.closure = sorted(set(closure.splitlines()))
        if not self.closure or any(
            not Path(path).is_dir() or Path(path).parent != Path("/nix/store")
            for path in self.closure
        ):
            raise RuntimeError(
                "Invalid Nix runtime closure; refusing broad host mounts"
            )
        self.test_library = None
        if python_test_library is not None:
            from python_test_library import CATALOG, load

            self.test_library = load(
                python_test_library,
                catalog=CATALOG if library_catalog is None else library_catalog,
            )
            closure = checked_command(
                [
                    tool_path("nix-store"),
                    "--query",
                    "--requisites",
                    *self.test_library["roots"],
                ]
            )
            extra = sorted(set(closure.splitlines()))
            if not extra or any(
                not Path(path).is_dir() or Path(path).parent != Path("/nix/store")
                for path in extra
            ):
                raise RuntimeError("Invalid test library runtime closure")
            self.test_library["closure"] = extra
        self.manifest = {
            "python": sys.version,
            "sqlite": sqlite3.sqlite_version,
            "bwrap": self.bwrap,
            "bwrap_version": checked_command([self.bwrap, "--version"]),
            "tools": self.tools,
            "tool_identity": {
                name: {
                    "invocation_path": path,
                    "resolved_path": str(Path(path).resolve()),
                    "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                }
                for name, path in self.tools.items()
            },
            "closure": self.closure,
            "worker_sha256": hashlib.sha256(WORKER.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "limits": {
                "workspace_bytes": WORK_BYTES,
                "workspace_entries": MAX_FILES,
                "tmpfs_bytes": 64 * 1024 * 1024,
                "memory_bytes": 512 * 1024 * 1024,
                "per_process_virtual_bytes": 2 * 1024 * 1024 * 1024,
                "tasks": 64,
                "cpu_quota": "200%",
                "raw_subprocess_output_bytes": 2 * 1024 * 1024,
            },
        }

        if self.test_library is not None:
            self.manifest["python_test_library"] = self.test_library

    def for_evaluation(self):
        """Reuse resolved base tools without agent-only test libraries.

        Behavioral probes use tool transport, so request mode alone does not
        identify the evaluator. Keep this view separate from the agent runtime.
        """
        if self.test_library is None:
            return self
        runtime = copy.copy(self)
        runtime.test_library = None
        runtime.manifest = self.manifest.copy()
        runtime.manifest.pop("python_test_library", None)
        return runtime

    def stop_scope(self, unit):
        records = []
        for operation in (("kill", "--kill-whom=all", "--signal=SIGKILL"), ("stop",)):
            try:
                result = subprocess.run(
                    [self.systemctl, "--user", *operation, unit],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                records.append(
                    {
                        "operation": list(operation),
                        "returncode": result.returncode,
                        "stderr": result.stderr,
                    }
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                records.append({"operation": list(operation), "error": str(error)})
        try:
            state = subprocess.run(
                [self.systemctl, "--user", "is-active", unit],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return {
                "unit": unit,
                "operations": records,
                "active_state": state.stdout.strip(),
                "returncode": state.returncode,
                "verified": state.returncode in (3, 4)
                and state.stdout.strip() in {"inactive", "failed", "unknown"},
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "unit": unit,
                "operations": records,
                "verified": False,
                "error": str(error),
            }

    def finalize_sandbox(self, unit, process, selector, streams, prefix):
        """Attempt every cleanup step; uncertainty is fatal even during cancellation."""
        cleanup = {"unit": unit, "verified": False}
        errors = []
        process_verified = process is None

        def record_error(operation, error):
            errors.append((operation, error))

        try:
            observed = self.stop_scope(unit)
            if isinstance(observed, dict):
                cleanup = observed
            else:
                record_error("stop_scope", TypeError("Missing scope cleanup receipt"))
        except BaseException as error:
            record_error("stop_scope", error)

        # Do not let a failed systemd command skip cleanup of our owned handle.
        running = process is not None
        if process is not None:
            try:
                running = process.poll() is None
            except BaseException as error:
                record_error("process_poll", error)
            if running:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except BaseException as error:
                    record_error("process_kill", error)
            try:
                process.wait(timeout=5)
                process_verified = True
            except BaseException as error:
                record_error("process_wait", error)

        closers = []
        if selector is not None:
            closers.append(("selector_close", selector.close))
        if process is not None:
            closers.extend(
                (name + "_close", getattr(process, name).close) for name in streams
            )
        for operation, close in closers:
            try:
                close()
            except BaseException as error:
                record_error(operation, error)

        cleanup = {
            **cleanup,
            "owned_process_started": process is not None,
            "owned_process_reaped": process_verified,
            "finalization_errors": [
                {"operation": op, "type": type(error).__name__, "message": str(error)}
                for op, error in errors
            ],
        }
        try:
            write_json(prefix.with_suffix(".cleanup.json"), cleanup)
        except BaseException as error:
            record_error("cleanup_receipt", error)
            emergency = {
                **cleanup,
                "receipt_error": {"type": type(error).__name__, "message": str(error)},
            }
            try:
                write_json(prefix.with_suffix(".cleanup-emergency.json"), emergency)
            except BaseException:
                try:
                    sys.stderr.write(
                        "Sandbox cleanup receipt: " + json.dumps(emergency) + "\n"
                    )
                    sys.stderr.flush()
                except BaseException:
                    pass
        for name, data in streams.items():
            try:
                prefix.with_suffix("." + name + ".bin").write_bytes(data)
            except BaseException as error:
                record_error(name + "_artifact", error)

        if cleanup.get("verified") is not True or not process_verified:
            fatal = UnsafeCleanup(f"Could not verify own sandbox cleanup: {unit}")
            for operation, error in errors:
                fatal.add_note(f"{operation}: {type(error).__name__}: {error}")
            raise fatal
        if errors:
            raise errors[0][1]
        return cleanup

    def sandbox(
        self,
        workspace,
        request,
        prefix,
        *,
        evaluation=None,
        observations=None,
        history_archive=None,
        scratch=None,
        checks=None,
    ):
        if scratch is not None and (
            request["mode"] != "tool" or evaluation is not None
        ):
            raise ValueError("Attempt scratch must not enter the evaluator")
        if request.get("persistent_scratch", False):
            raise ValueError("Scratch policy is owned by the runtime")
        if scratch is not None:
            request = {**request, "persistent_scratch": True}
        if history_archive is not None and request["mode"] != "tool":
            raise ValueError("Conversation history must not enter the evaluator")
        if checks is not None and request["mode"] != "tool":
            raise ValueError("Check records must not enter the evaluator")
        timeout = request["timeout"] + 5
        # Each action gets its own quota-limited cgroup and private namespaces.
        unit = "big-model-agent-" + uuid.uuid4().hex + ".scope"
        request_path = prefix.with_suffix(".request.json")
        write_json(request_path, request)
        command = [
            self.systemd_run,
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            "--unit=" + unit,
            "--property=MemoryMax=536870912",
            "--property=MemorySwapMax=0",
            "--property=TasksMax=64",
            "--property=CPUQuota=200%",
            f"--property=RuntimeMaxSec={math.ceil(timeout)}",
            "--",
            self.bwrap,
            "--unshare-all",
            "--as-pid-1",
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--disable-userns",
            "--assert-userns-disabled",
            "--cap-drop",
            "ALL",
            "--dir",
            "/nix/store",
            "--dir",
            "/bin",
        ]
        library = (
            getattr(self, "test_library", None) if request["mode"] == "tool" else None
        )
        closure = set(self.closure)
        if library is not None:
            closure.update(library["closure"])
        for path in sorted(closure):
            command.extend(("--ro-bind", path, path))
        for name, path in sorted(self.tools.items()):
            command.extend(("--symlink", path, "/bin/" + name))
        command.extend(
            (
                "--ro-bind",
                str(WORKER),
                "/worker.py",
                "--ro-bind",
                str(request_path),
                "/request.json",
                "--proc",
                "/proc",
                "--remount-ro",
                "/proc",
                "--dev",
                "/dev",
                "--size",
                str(64 * 1024 * 1024),
                "--tmpfs",
                "/tmp",
            )
        )
        if scratch is None:
            command.extend(("--dir", "/tmp/home"))
        else:
            scratch_export = prefix.with_suffix(".scratch.tar")
            scratch_export.touch(exist_ok=False)
            command.extend(
                (
                    "--ro-bind",
                    str(scratch),
                    "/scratch-input",
                    "--bind",
                    str(scratch_export),
                    "/scratch-export.tar",
                )
            )
        export_path = None
        if request["mode"] == "tool":
            if observations is not None:
                archive = validate_observation_archive(observations, prefix)
                command.extend(("--ro-bind", str(archive), "/observations"))
            if checks is not None:
                from run_checks import validate_archive

                archive = validate_archive(checks, prefix)
                command.extend(("--ro-bind", str(archive), "/checks"))
            if history_archive is not None:
                archive = validate_history_archive(history_archive, prefix)
                command.extend(("--ro-bind", str(archive), "/history"))
            export_path = prefix.with_suffix(".workspace.tar")
            export_path.touch(exist_ok=False)
            command.extend(
                (
                    "--ro-bind",
                    str(workspace),
                    "/input",
                    "--size",
                    str(WORK_BYTES),
                    "--tmpfs",
                    "/workspace",
                    "--bind",
                    str(export_path),
                    "/export.tar",
                )
            )
        else:
            if observations is not None:
                raise ValueError("Observation archive must not enter the evaluator")
            command.extend(("--ro-bind", str(workspace), "/workspace"))
            if evaluation:
                source, target = evaluation
                command.extend(("--ro-bind", str(source), target))
        command.extend(("--remount-ro", "/", "--chdir", "/workspace", "--clearenv"))
        if library is not None:
            command.extend(
                ("--setenv", "HYPOTHESIS_STORAGE_DIRECTORY", "/tmp/hypothesis")
            )
        for name, value in {
            "PATH": "/bin",
            "HOME": "/tmp/home",
            "TMPDIR": "/tmp",
            "PYTHONPATH": ":".join(
                ["/workspace", *(library["python_paths"] if library else [])]
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_AUTHOR_NAME": "Local Developer",
            "GIT_AUTHOR_EMAIL": "developer@example.invalid",
            "GIT_COMMITTER_NAME": "Local Developer",
            "GIT_COMMITTER_EMAIL": "developer@example.invalid",
        }.items():
            command.extend(("--setenv", name, value))
        command.extend((self.python, "-I", "-S", "/worker.py"))
        write_json(
            prefix.with_suffix(".invocation.json"),
            {"unit": unit, "argv": command, "timeout_seconds": timeout},
        )
        started = time.monotonic()
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        process = selector = None
        limit_reason = None
        try:
            with defer_launch_signals():
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            selector = selectors.DefaultSelector()
            for name in streams:
                selector.register(getattr(process, name), selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    limit_reason = "sandbox_wall_limit"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    available = 2 * 1024 * 1024 - sum(
                        len(data) for data in streams.values()
                    )
                    streams[key.data].extend(chunk[:available])
                    if len(chunk) > available:
                        limit_reason = "sandbox_output_limit"
                        break
                if limit_reason:
                    break
            process.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
        finally:
            with protected_cleanup():
                self.finalize_sandbox(unit, process, selector, streams, prefix)
        if limit_reason or process.returncode:
            raise RuntimeError(
                f"Sandbox failed closed: {limit_reason or process.returncode}; see {prefix.name} traces"
            )
        result = json.loads(streams["stdout"])
        if not isinstance(result, dict):
            raise TypeError("Sandbox transport did not return a JSON object")
        write_json(prefix.with_suffix(".result.json"), result)
        return result, export_path


def _unpack_snapshot(archive_path, destination):
    if archive_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Oversized snapshot archive")
    destination.mkdir(exist_ok=False)
    total, seen = 0, set()
    with tarfile.open(archive_path, "r:") as archive:
        for index, member in enumerate(archive):
            path = Path(member.name)
            if (
                index >= MAX_FILES
                or not member.name
                or member.size < 0
                or path.is_absolute()
                or ".." in path.parts
                or member.name in seen
                or not (member.isdir() or member.isreg())
            ):
                raise ValueError("Unsafe snapshot entry")
            seen.add(member.name)
            target = destination / path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if total > WORK_BYTES:
                raise ValueError("Oversized workspace snapshot")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=65536)
            # Git tracks executability. Preserve that ordinary file property,
            # while retaining safe permissions and discarding setuid/setgid bits.
            target.chmod(0o644 | (member.mode & 0o111))
    return destination


def unpack_snapshot(archive_path, destination):
    pending = destination.with_name(".pending-" + uuid.uuid4().hex)
    try:
        _unpack_snapshot(archive_path, pending)
        pending.rename(destination)
    except BaseException:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    return destination


class ScratchState:
    """Outer-owned, attempt-local scratch generations; never evaluator input."""

    def __init__(self, root):
        self.current = root / "0000"
        self.current.mkdir(parents=True, exist_ok=False)
        (self.current / "home").mkdir()


def import_tool_snapshots(archive, updated, scratch_archive, scratch):
    """Validate both states before advancing either caller-visible generation."""
    scratch_updated = scratch.current.parent / updated.name
    if updated.exists() or scratch_updated.exists():
        raise ValueError("Tool snapshot generation already exists")
    workspace_pending = updated.with_name(".pending-" + uuid.uuid4().hex)
    scratch_pending = scratch_updated.with_name(".pending-" + uuid.uuid4().hex)
    published = []
    try:
        _unpack_snapshot(archive, workspace_pending)
        _unpack_snapshot(scratch_archive, scratch_pending)
        workspace_pending.rename(updated)
        published.append(updated)
        scratch_pending.rename(scratch_updated)
        published.append(scratch_updated)
    except BaseException:
        for path in [workspace_pending, scratch_pending, *published]:
            shutil.rmtree(path, ignore_errors=True)
        raise
    scratch.current = scratch_updated


def perform_tool(
    runtime,
    workspace,
    name,
    arguments,
    timeout,
    prefix,
    *,
    observations=None,
    history_archive=None,
    max_command_bytes=8192,
    scratch=None,
    checks=None,
    public_interface=None,
):
    if type(max_command_bytes) is not int or not 8192 <= max_command_bytes <= 32768:
        raise ValueError("Invalid trusted max_command_bytes")
    options = {"observations": observations} if observations is not None else {}
    if history_archive is not None:
        options["history_archive"] = history_archive
    if checks is not None:
        options["checks"] = checks
    if scratch is not None:
        if (
            not isinstance(scratch, ScratchState)
            or scratch.current.name != workspace.name
        ):
            raise ValueError("Scratch and workspace generations must match")
        options["scratch"] = scratch.current
    result, archive = runtime.sandbox(
        workspace,
        {
            "mode": "tool",
            "name": name,
            "arguments": arguments,
            "timeout": timeout,
            "max_command_bytes": max_command_bytes,
            **({"public_interface": public_interface} if public_interface else {}),
        },
        prefix,
        **options,
    )
    if result.get("snapshot_error") or not archive:
        raise RuntimeError(
            "Invalid workspace snapshot; preserving last valid snapshot and stopping"
        )
    updated = workspace.parent / f"{int(workspace.name) + 1:04d}"
    if scratch is None:
        unpack_snapshot(archive, updated)
    else:
        if not result.get("scratch_snapshot"):
            raise RuntimeError("Missing scratch snapshot; preserving last valid states")
        import_tool_snapshots(
            archive, updated, prefix.with_suffix(".scratch.tar"), scratch
        )
    return result, updated
