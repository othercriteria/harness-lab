"""Trusted inner worker for agent_harness; execute only inside its namespaces."""

import contextlib
import ctypes
import errno
import json
import os
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

WORK_BYTES = 16 * 1024 * 1024
OUTPUT_BYTES = 128 * 1024
MAX_FILES = 2048
WORKSPACE = Path("/workspace")
QUIESCENCE_SECONDS = 2
MAX_COMMAND_BYTES = 32768
EDIT_TEXT_BYTES = 32768
EDIT_FILE_BYTES = 262144
WRITE_TEXT_BYTES = 32768


class EditError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.details = {"code": code, "message": message, **details}


def _text_sizes(arguments, fields):
    if not isinstance(arguments, dict) or arguments.keys() != set(fields):
        raise EditError("ARGUMENTS", "Expected exactly " + ", ".join(fields))
    if any(not isinstance(value, str) for value in arguments.values()):
        raise EditError("ARGUMENTS", "File tool fields must be strings")
    try:
        sizes = {key: len(value.encode("utf-8")) for key, value in arguments.items()}
    except UnicodeError as error:
        raise EditError("NOT_UTF8", "File tool fields must be valid UTF-8") from error
    if not 1 <= sizes["path"] <= 1024 or "\x00" in arguments["path"]:
        raise EditError(
            "PATH_NOT_ALLOWED", "Path must contain 1–1024 UTF-8 bytes and no NUL"
        )
    return sizes


def validate_write_arguments(arguments):
    sizes = _text_sizes(arguments, ("path", "content"))
    if sizes["content"] > WRITE_TEXT_BYTES:
        raise EditError(
            "WRITE_TOO_LARGE", f"Content exceeds {WRITE_TEXT_BYTES} UTF-8 bytes"
        )
    return arguments


def validate_edit_arguments(arguments):
    sizes = _text_sizes(arguments, ("path", "old_text", "new_text"))
    if not sizes["old_text"]:
        raise EditError("EMPTY_OLD_TEXT", "old_text must be nonempty")
    combined = sizes["old_text"] + sizes["new_text"]
    if combined > EDIT_TEXT_BYTES:
        raise EditError(
            "EDIT_TOO_LARGE",
            "Combined edit text exceeds its byte limit",
            actual_bytes=combined,
            maximum_bytes=EDIT_TEXT_BYTES,
        )
    return arguments


def _mutation_path(root, name):
    # Path() drops a trailing slash or dot, and abspath() also cancels "..".
    # Check directory intent and walk each named parent before resolving "..".
    path = root / name
    if (
        name.rsplit("/", 1)[-1] in ("", ".", "..")
        or not path.is_relative_to(root)
        or path == root
    ):
        raise EditError(
            "PATH_NOT_ALLOWED", "Path must identify a file inside /workspace"
        )
    current = root
    for part in path.relative_to(root).parts[:-1]:
        if part == "..":
            if current == root:
                raise EditError("PATH_NOT_ALLOWED", "Path must stay inside /workspace")
            current = current.parent
        else:
            current /= part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError as error:
                raise EditError(
                    "PARENT_NOT_FOUND",
                    "Parent directory does not exist. Create parent directories "
                    "with bash mkdir, then retry; file contents were not saved.",
                ) from error
            if not stat.S_ISDIR(mode):
                raise EditError(
                    "PATH_NOT_ALLOWED",
                    "Parents must be existing non-symlink directories",
                )
    return current / path.name


def _read_mutation_target(path, *, allow_create=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_create:
            return None, 0o644
        raise
    if stat.S_ISLNK(info.st_mode) and not allow_create:
        raise EditError("PATH_NOT_ALLOWED", "Symlink components are not editable")
    if not stat.S_ISREG(info.st_mode):
        raise EditError("NOT_REGULAR_FILE", "Target must be a regular non-symlink file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode) & 0o777
        data = stream.read(EDIT_FILE_BYTES + 1)
    if len(data) > EDIT_FILE_BYTES:
        raise EditError(
            "FILE_TOO_LARGE",
            "Existing file exceeds its byte limit",
            maximum_bytes=EDIT_FILE_BYTES,
        )
    try:
        data.decode("utf-8")  # Validate without translating newline or BOM bytes.
    except UnicodeError as error:
        raise EditError("NOT_UTF8", "Existing file is not strict UTF-8") from error
    return data, mode


def _replace_bytes(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix=".harness-file-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_file(arguments):
    """Atomic bounded UTF-8 write inside the isolated worker; no shell parsing."""
    validate_write_arguments(arguments)
    root = WORKSPACE.resolve()
    try:
        path = _mutation_path(root, arguments["path"])
        original, mode = _read_mutation_target(path, allow_create=True)
        content = arguments["content"].encode("utf-8")
        changed = original != content
        if changed:
            _replace_bytes(path, content, mode)
        return {
            "ok": True,
            "changed": changed,
            "created": original is None,
            "path": str(path.relative_to(root)),
            "before_bytes": len(original) if original is not None else 0,
            "after_bytes": len(content),
        }
    except OSError as error:
        raise EditError("IO_ERROR", str(error)[:300]) from error


def edit_file(arguments):
    """Replace one exact match in an existing workspace file, counting overlaps."""
    validate_edit_arguments(arguments)
    root = WORKSPACE.resolve()
    try:
        path = _mutation_path(root, arguments["path"])
        data, mode = _read_mutation_target(path)
        old, new = (arguments[k].encode("utf-8") for k in ("old_text", "new_text"))
        count, start, found = 0, 0, -1
        while (offset := data.find(old, start)) != -1:
            count += 1
            found = offset
            start = offset + 1
        if count != 1:
            raise EditError(
                "MATCH_COUNT",
                "No edit applied; provide unique exact text from the current file",
                expected=1,
                actual=count,
            )
        replacement = data[:found] + new + data[found + len(old) :]
        if len(replacement) > EDIT_FILE_BYTES:
            raise EditError(
                "FILE_TOO_LARGE",
                "Result exceeds edit file limit",
                actual_bytes=len(replacement),
                maximum_bytes=EDIT_FILE_BYTES,
            )
        changed = replacement != data
        if changed:
            _replace_bytes(path, replacement, mode)
        return {
            "ok": True,
            "changed": changed,
            "path": str(path.relative_to(root)),
            "matches": 1,
            "before_bytes": len(data),
            "after_bytes": len(replacement),
        }
    except OSError as error:
        raise EditError("IO_ERROR", str(error)[:300]) from error


class QuiescenceError(RuntimeError):
    """The worker must exit without exporting when descendant cleanup is uncertain."""


def require_namespace_init():
    # This must remain a runtime check, including under python -O. In particular,
    # never permit the namespace-wide kill below in an ordinary host process.
    if os.getpid() != 1:
        raise RuntimeError("Trusted worker requires its own PID namespace as PID 1")


def protect_worker():
    require_namespace_init()
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_DUMPABLE / PR_GET_DUMPABLE. A child's exec or prctl affects that
    # child only; keep the worker's transport descriptors inaccessible via /proc.
    if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:
        raise RuntimeError("Cannot protect trusted worker process descriptors")


@contextlib.contextmanager
def blocked_cleanup_signals():
    previous = signal.pthread_sigmask(
        signal.SIG_BLOCK,
        {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM},
    )
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def quiesce_descendants(process=None):
    """Kill and reap all namespace descendants before any workspace export."""
    require_namespace_init()
    started = time.monotonic()
    end = started + QUIESCENCE_SECONDS
    reaped = 0

    def kill_all():
        try:
            os.kill(-1, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        with blocked_cleanup_signals():
            kill_all()
            if process is not None:
                # Generic waitpid must not consume Popen's direct-child status.
                process.wait(timeout=max(0.001, end - time.monotonic()))
            while True:
                if time.monotonic() >= end:
                    raise TimeoutError("Namespace descendants did not quiesce")
                kill_all()
                try:
                    # Linux __WALL also includes children created with unusual
                    # clone exit signals. PID 1 adopts orphaned descendants.
                    pid, _ = os.waitpid(-1, os.WNOHANG | 0x40000000)
                except ChildProcessError:
                    break
                if pid:
                    reaped += 1
                else:
                    time.sleep(0.005)
    except BaseException as error:
        raise QuiescenceError("Cannot verify namespace descendant cleanup") from error
    return {
        "verified": True,
        "reaped_descendants": reaped,
        "wall_seconds": time.monotonic() - started,
    }


def restrict_syscalls():
    """Deny network/namespace/ptrace interfaces; retain shells, threads and Python."""
    if os.uname().machine != "x86_64":
        raise RuntimeError("Sandbox seccomp profile requires native x86-64")

    class Filter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_ushort),
            ("jt", ctypes.c_ubyte),
            ("jf", ctypes.c_ubyte),
            ("k", ctypes.c_uint),
        ]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("filters", ctypes.POINTER(Filter))]

    denied = 0x00050000 | errno.EPERM
    instructions = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
        (0x35, 0, 1, 0x40000000),
        (0x06, 0, 0, denied),
    ]
    # socket/connect/accept/bind/listen/socketpair, namespaces/mounts, ptrace,
    # cross-process memory/fds, kernel programming and alternate async I/O.
    for number in (
        41,
        42,
        43,
        49,
        50,
        53,
        101,
        165,
        166,
        169,
        175,
        176,
        246,
        248,
        249,
        250,
        272,
        288,
        298,
        303,
        304,
        308,
        310,
        311,
        313,
        320,
        321,
        323,
        425,
        426,
        427,
        428,
        429,
        430,
        431,
        432,
        433,
        438,
        442,
    ):
        instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, denied)))
    # Return ENOSYS for clone3 so libc can use the filtered legacy clone call.
    instructions.extend(((0x15, 0, 1, 435), (0x06, 0, 0, 0x00050000 | errno.ENOSYS)))
    instructions.extend(
        (
            (0x15, 0, 4, 56),
            (0x20, 0, 0, 16),
            (0x54, 0, 0, 0x7E020000),
            (0x15, 1, 0, 0),
            (0x06, 0, 0, denied),
            (0x06, 0, 0, 0x7FFF0000),
        )
    )
    filters = (Filter * len(instructions))(*(Filter(*item) for item in instructions))
    program = Program(len(filters), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise OSError(ctypes.get_errno(), "Cannot install fail-closed seccomp profile")


def file_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("File paths must be nonempty strings within /workspace")
    candidate = Path(value)
    path = (candidate if candidate.is_absolute() else WORKSPACE / candidate).resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError("Path escapes workspace")
    return path


def run_command(argv, timeout, *, cleanup=None):
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    reason = None
    selector = selectors.DefaultSelector()
    try:
        for name in streams:
            selector.register(getattr(process, name), selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                reason = "tool_wall_limit"
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                remaining_output = OUTPUT_BYTES - sum(
                    len(value) for value in streams.values()
                )
                streams[key.data].extend(chunk[:remaining_output])
                if len(chunk) > remaining_output:
                    reason = "tool_output_limit"
                    break
            if reason:
                break
    finally:
        try:
            quiescence = (cleanup or quiesce_descendants)(process)
        finally:
            selector.close()
            for name in streams:
                getattr(process, name).close()
    result = {
        name: bytes(value).decode("utf-8", errors="replace")
        for name, value in streams.items()
    }
    result.update(
        returncode=process.returncode,
        wall_seconds=time.monotonic() - started,
        stopped_by=reason,
        quiescence=quiescence,
    )
    return result


def export_tree(root, destination):
    entries = []
    regular_files = 0
    total = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in sorted(directories + names):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError("Snapshots allow only regular files/directories")
            if stat.S_ISREG(mode):
                regular_files += 1
                total += path.stat().st_size
            entries.append(path)
            # Aggregate limit: every archive entry (files and directories)
            # counts toward MAX_FILES and regular-file contents toward WORK_BYTES.
            if len(entries) > MAX_FILES or total > WORK_BYTES:
                raise ValueError("Snapshot size/file-count limit exceeded")
    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as archive:
        for path in entries:
            member = archive.gettarinfo(path, arcname=str(path.relative_to(root)))
            # PAX decimal seconds preserve nanoseconds without a float roundtrip.
            stamp = path.stat().st_mtime_ns
            seconds, nanos = divmod(abs(stamp), 1_000_000_000)
            member.mtime = stamp // 1_000_000_000
            member.pax_headers["mtime"] = (
                f"{'-' if stamp < 0 else ''}{seconds}.{nanos:09d}"
            )
            if member.isreg():
                with path.open("rb") as source:
                    archive.addfile(member, source)
            else:
                archive.addfile(member)
    return {
        "entries": len(entries),
        "regular_files": regular_files,
        "file_bytes": total,
    }


def export_workspace():
    return export_tree("/workspace", "/export.tar")


def main():
    protect_worker()
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024,) * 2)
    request = json.loads(Path("/request.json").read_text())
    mode = request["mode"]
    persistent_scratch = request.get("persistent_scratch", False)
    if type(persistent_scratch) is not bool or (persistent_scratch and mode != "tool"):
        raise ValueError("Invalid trusted scratch policy")
    if mode == "tool":
        shutil.copytree("/input", "/workspace", dirs_exist_ok=True, symlinks=False)
        if persistent_scratch:
            shutil.copytree(
                "/scratch-input", "/tmp", dirs_exist_ok=True, symlinks=False
            )
    restrict_syscalls()
    started = time.monotonic()
    result = {"ok": False}
    try:
        if mode == "grade":
            result = run_command(request["argv"], request["timeout"])
            result["ok"] = result["returncode"] == 0 and result["stopped_by"] is None
        elif mode == "tool":
            name, arguments = request["name"], request["arguments"]
            if name == "execute":
                command = arguments["command"]
                # This top-level field is owned by the outer harness. Model tool
                # arguments cannot override it; the worker retains its hard ceiling.
                command_limit = request.get("max_command_bytes", 8192)
                if (
                    type(command_limit) is not int
                    or not 8192 <= command_limit <= MAX_COMMAND_BYTES
                ):
                    raise ValueError("Invalid trusted max_command_bytes")
                if (
                    not isinstance(command, str)
                    or len(command.encode()) > command_limit
                ):
                    raise ValueError(
                        f"Shell command exceeds {command_limit}-byte limit"
                    )
                result = run_command(
                    ["/bin/bash", "--noprofile", "--norc", "-c", command],
                    request["timeout"],
                )
                result["ok"] = (
                    result["returncode"] == 0 and result["stopped_by"] is None
                )
            elif name in ("edit_file", "write_file"):
                try:
                    edited = (
                        edit_file(arguments)
                        if name == "edit_file"
                        else write_file(arguments)
                    )
                except EditError as error:
                    edited = {"ok": False, "error": error.details}
                result = {
                    "ok": edited["ok"],
                    "returncode": 0 if edited["ok"] else 1,
                    "stdout": json.dumps(edited, ensure_ascii=True),
                    "stderr": "",
                }
            elif name == "read_file":
                with file_path(arguments["path"]).open("rb") as stream:
                    data = stream.read(65537)
                result = {
                    "ok": True,
                    "content": data[:65536].decode("utf-8", errors="replace"),
                    "truncated": len(data) > 65536,
                }
            else:
                raise ValueError("Unknown tool")
        else:
            raise ValueError("Unknown worker mode")
    except QuiescenceError:
        # Never turn uncertain cleanup into an otherwise importable snapshot.
        raise
    except BaseException as error:  # noqa: BLE001 - transport all boundary failures
        result = {
            "ok": False,
            "error": {"type": type(error).__name__, "message": str(error)},
        }
    # Also cover failures before run_command returned, and non-command tools.
    # Interrupts stay blocked through export; only the outer scope may kill us.
    with blocked_cleanup_signals():
        result["final_quiescence"] = quiesce_descendants()
        if mode == "tool":
            try:
                result["snapshot"] = export_workspace()
                if persistent_scratch:
                    result["scratch_snapshot"] = export_tree(
                        "/tmp", "/scratch-export.tar"
                    )
            except BaseException as error:  # noqa: BLE001
                result["ok"] = False
                result["snapshot_error"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
    result["worker_wall_seconds"] = time.monotonic() - started
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
