"""Recorded isolated checks; file identities are evidence, never correctness claims."""

import hashlib
import json
import os
import re
import shlex
import stat
from pathlib import Path

from read_file import read_bytes
from spec_blocker import _constant, _object

NAME = "run_checks"
MAX_COMMAND_BYTES = 8192
MAX_FILES = 2048
MAX_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
INSTRUCTION = (
    " Use run_checks(command, cwd) for verification commands. It runs in the same"
    " isolated environment as bash and records exit status, before/after file"
    " identities and available Git HEAD metadata. Use a repository root as cwd"
    " for Git checks. Cite its observation ID in checkpoints and finish_attempt."
    " Read-only /checks/cNNNN.json records let bash scripts copy recorded revision"
    " IDs into delivery files without manual transcription. Records are historical:"
    " a zero exit status does not establish coverage or correctness, and observed"
    " Git HEAD alone does not prove a clean committed tree."
)
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": (
            "Run a verification command and save a historical check record. Same"
            " isolation, timeout and output bounds as bash. Records the selected"
            " directory's regular files before/after (excluding .git), observed Git"
            " HEAD, exit status and displayed output. This is not a correctness"
            " certification. Compound commands must preserve relevant exit status."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "cwd"],
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to check the work; command plus cwd wrapper must fit 8192 UTF-8 bytes.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Directory under /workspace; use the repository root for Git checks.",
                },
            },
        },
    },
}


def validate(value):
    if not isinstance(value, dict) or set(value) != {"command", "cwd"}:
        raise ValueError("run_checks requires command and cwd")
    command, cwd = value["command"], value["cwd"]
    if (
        not isinstance(command, str)
        or not command.strip()
        or "\0" in command
        or len(command.encode()) > MAX_COMMAND_BYTES
    ):
        raise ValueError("Check command must be nonempty text of at most 8192 bytes")
    if not isinstance(cwd, str) or not cwd or "\0" in cwd or len(cwd.encode()) > 512:
        raise ValueError("Invalid check directory")
    if cwd in (".", "/workspace", "/workspace/"):
        cwd = "."
    else:
        if cwd.startswith("/workspace/"):
            cwd = cwd[len("/workspace/") :]
        if cwd.startswith("/") or any(p in ("", ".", "..") for p in cwd.split("/")):
            raise ValueError(
                "Check directory must stay inside /workspace without traversal"
            )
    normalized = {"command": command, "cwd": cwd}
    if len(_shell_command(normalized).encode()) > MAX_COMMAND_BYTES:
        raise ValueError(
            "Check command plus cwd wrapper exceeds 8192 UTF-8 bytes; shorten the command"
        )
    return normalized


def action(call):
    raw = call["function"]["arguments"]
    if not isinstance(raw, str) or len(raw.encode()) > 65536:
        raise ValueError("Oversized run_checks arguments")
    arguments = validate(
        json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    )
    return {
        "tool": NAME,
        "arguments": arguments,
        "tool_call_id": call["id"],
        "command": NAME + " " + json.dumps(arguments, ensure_ascii=True),
    }


def shell_command(arguments):
    args = validate(arguments)
    return _shell_command(args)


def _shell_command(args):
    cwd = "/workspace" + ("/" + args["cwd"] if args["cwd"] != "." else "")
    return "cd " + shlex.quote(cwd) + " && (\n" + args["command"] + "\n)"


def git_head(workspace, cwd):
    """Read bounded metadata as data; never invoke host Git or load its config."""
    base = (cwd + "/" if cwd != "." else "") + ".git/"
    try:
        head = read_bytes(workspace, base + "HEAD").decode("ascii").strip()
        branch = None
        if head.startswith("ref: "):
            ref = head[5:]
            if not re.fullmatch(r"refs/heads/[A-Za-z0-9_./-]{1,200}", ref) or any(
                p in ("", ".", "..") for p in ref.split("/")
            ):
                return {"status": "unavailable"}
            branch = ref[len("refs/heads/") :]
            try:
                head = read_bytes(workspace, base + ref).decode("ascii").strip()
            except FileNotFoundError:
                lines = (
                    read_bytes(workspace, base + "packed-refs")
                    .decode("ascii")
                    .splitlines()
                )
                values = [
                    line.split(" ")[0] for line in lines if line.endswith(" " + ref)
                ]
                if len(values) != 1:
                    return {"status": "unavailable"}
                head = values[0]
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
            return {"status": "unavailable"}
        return {"status": "observed_reference_only", "branch": branch, "commit": head}
    except (OSError, UnicodeError, ValueError):
        return {"status": "unavailable"}


def identity(workspace, cwd):
    """Hash normalized snapshot data through no-follow directory descriptors."""
    cwd = validate({"command": "true", "cwd": cwd})["cwd"]
    descriptor = None
    try:
        descriptor = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if cwd != ".":
            for part in cwd.split("/"):
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
        rows = []
        count = total = 0

        def walk(directory, relative, depth):
            nonlocal count, total
            if depth > 32:
                raise ValueError("Directory depth limit")
            with os.scandir(directory) as entries:
                names = []
                for entry in entries:
                    count += 1
                    if count > MAX_FILES:
                        raise ValueError("File count limit")
                    names.append(entry.name)
            for name in sorted(names):
                if name == ".git":
                    continue
                path = relative + name
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory,
                    )
                    try:
                        rows.append([path, "directory"])
                        walk(child, path + "/", depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if total > MAX_BYTES:
                        raise ValueError("Byte limit")
                    data = read_bytes(
                        workspace, (cwd + "/" if cwd != "." else "") + path
                    )
                    rows.append(
                        [path, info.st_mode & 0o111, hashlib.sha256(data).hexdigest()]
                    )
                else:
                    raise ValueError("Nonregular snapshot entry")

        walk(descriptor, "", 0)
        return {
            "status": "captured",
            "tree_sha256": hashlib.sha256(
                json.dumps(rows, ensure_ascii=True).encode()
            ).hexdigest(),
            "entries": len(rows),
            "bytes": total,
            "git_head": git_head(workspace, cwd),
        }
    except (OSError, ValueError, UnicodeError):
        return {"status": "unavailable"}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def save(directory, number, arguments, before, after, output):
    identifier = f"c{number:04d}"
    summary = {
        "id": identifier,
        "record_path": f"/checks/{identifier}.json",
        "cwd": arguments["cwd"],
        "before": before,
        "after": after,
        "files_unchanged": before.get("status") == after.get("status") == "captured"
        and before["tree_sha256"] == after["tree_sha256"],
        "returncode": output["returncode"],
    }
    record = {
        **summary,
        "command": arguments["command"],
        "output": output["output"],
        "truncated": output["truncated"],
        "exception_info": output["exception_info"],
        "scope": "Historical command boundary snapshots of cwd, excluding .git. No claim about transient edits, dependencies elsewhere, committed-tree cleanliness, coverage or correctness.",
    }
    data = json.dumps(record, ensure_ascii=True).encode()
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError("Check record byte limit")
    with (Path(directory) / (identifier + ".json")).open("xb") as stream:
        stream.write(data)
    return summary


def validate_archive(directory, prefix):
    archive = Path(directory)
    if (
        archive.is_symlink()
        or archive.resolve() != (prefix.parent / "checks").resolve()
    ):
        raise ValueError("Check archive must belong to this attempt")
    count = total = 0
    for path in archive.iterdir():
        count += 1
        info = path.lstat()
        total += info.st_size
        if (
            count > 128
            or total > MAX_ARCHIVE_BYTES
            or not stat.S_ISREG(info.st_mode)
            or not re.fullmatch(r"c[0-9]{4}\.json", path.name)
            or info.st_size > MAX_RECORD_BYTES
        ):
            raise ValueError("Invalid bounded check archive")
    return archive
