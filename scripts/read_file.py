"""Bounded text reads from normalized workspace snapshots; never execute files."""

import hashlib
import io
import json
import os
import stat
from pathlib import PurePosixPath

from spec_blocker import _constant, _object

NAME = "read_file"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_CHARS = 10000
INSTRUCTION = (
    " Use read_file for bounded reads of UTF-8 workspace files. Returned text"
    " preserves file contents without line-number prefixes; range metadata uses"
    " one-based lines. start_line is one-based; max_lines defaults to 200. Bash remains available"
    " for searches and combined inspections."
)
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": (
            "Read current UTF-8 file contents inside /workspace without executing"
            " a shell or changing files. Returns plain file text, one-based line range and exact file"
            " identity; at most 400 lines and 10000 output characters."
            " With duplicate suppression enabled, an unchanged requested range"
            " already present in your current context may be referenced by"
            " observation ID; set reread=true to return the text again."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative workspace path or /workspace/path.",
                },
                "start_line": {"type": "integer", "minimum": 1, "maximum": 1000000},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 400},
                "reread": {
                    "type": "boolean",
                    "description": "Return contents even if already in the current context.",
                },
            },
        },
    },
}


def validate(value):
    if (
        not isinstance(value, dict)
        or "path" not in value
        or set(value) - {"path", "start_line", "max_lines", "reread"}
    ):
        raise ValueError(
            "read_file requires path; optional start_line, max_lines, reread"
        )
    path = value["path"]
    if (
        not isinstance(path, str)
        or not path
        or len(path.encode()) > 4096
        or "\x00" in path
    ):
        raise ValueError("Invalid workspace file path")
    if path in ("/workspace", "/workspace/", ".", "./"):
        raise ValueError(
            "read_file needs a file, not the workspace directory. "
            "Use execute with command 'ls /workspace' to list files, "
            "then pass a file path to read_file."
        )
    if path.startswith("/workspace/"):
        path = path[len("/workspace/") :]
    if path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
        raise ValueError("Path must stay inside /workspace without traversal")
    for key, default, maximum in (("start_line", 1, 1000000), ("max_lines", 200, 400)):
        n = value.get(key, default)
        if type(n) is not int or not 1 <= n <= maximum:
            raise ValueError(f"Invalid {key}")
    if type(value.get("reread", False)) is not bool:
        raise ValueError("reread must be boolean")
    return {
        "path": path,
        "start_line": value.get("start_line", 1),
        "max_lines": value.get("max_lines", 200),
        "reread": value.get("reread", False),
    }


def action(call):
    raw = call["function"]["arguments"]
    if not isinstance(raw, str) or len(raw.encode()) > 8192:
        raise ValueError("read_file arguments exceed 8192 bytes")
    arguments = validate(
        json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    )
    return {
        "tool": NAME,
        "arguments": arguments,
        "tool_call_id": call["id"],
        "command": NAME + " " + json.dumps(arguments, ensure_ascii=True),
    }


def read_bytes(workspace, path):
    """Walk through directory FDs with no symlink following, including final file."""
    directory = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(path).parts
        for part in parts[:-1]:
            successor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = successor
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
                raise ValueError("read_file requires a regular file of at most 16 MiB")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise ValueError("File exceeds 16 MiB")
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def read(workspace, arguments):
    value = validate(arguments)
    try:
        data = read_bytes(workspace, value["path"])
        text = data.decode("utf-8")
        if "\x00" in text:
            raise ValueError("read_file supports UTF-8 text without NUL bytes")
    except (OSError, ValueError) as error:
        display_path = "/workspace/" + value["path"]
        if len(display_path) > 240:
            display_path = display_path[:240] + "..."
        return {
            "returncode": 1,
            "output": (
                f"{type(error).__name__}: unable to read a bounded regular UTF-8 file at "
                + json.dumps(display_path, ensure_ascii=True)
                + ". Paths are relative to /workspace (for example src/app.py),"
                " or absolute /workspace/src/app.py."
            ),
            "truncated": False,
            "exception_info": type(error).__name__,
        }
    first = value["start_line"]
    last = first + value["max_lines"] - 1
    chunks = []
    characters = 0
    total_lines = 0
    last_returned = None
    partial_line = False
    for number, line in enumerate(io.StringIO(text, newline=""), 1):
        total_lines = number
        if first <= number <= last and characters < MAX_OUTPUT_CHARS:
            rendered = line
            room = MAX_OUTPUT_CHARS - characters
            chunks.append(rendered[:room])
            characters += min(len(rendered), room)
            last_returned = number
            partial_line = len(rendered) > room
    clipped = partial_line or (last_returned or first - 1) < min(last, total_lines)
    metadata = {
        "path": "/workspace/" + value["path"],
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "file_bytes": len(data),
        "start_line": first,
        "max_lines": value["max_lines"],
        "last_returned_line": last_returned,
        "total_lines": total_lines,
        "partial_last_line": partial_line,
        "range_clipped": clipped,
        "contents_returned": True,
    }
    return {
        "returncode": 0,
        "output": "".join(chunks),
        "truncated": clipped,
        "exception_info": "",
        "file_read": metadata,
    }


def verify_receipt(prefix):
    """Audit trusted non-executing reads without accepting arbitrary cleanup skips."""
    records = []
    for suffix in ("request", "result"):
        path = prefix.with_suffix(f".{suffix}.json")
        if path.is_symlink() or path.stat().st_size > 131072:
            raise ValueError("Invalid read_file receipt")
        records.append(json.loads(path.read_text()))
    request, result = records
    if not (
        request.get("mode") == "adapter-read"
        and request.get("name") == NAME
        and request.get("executed") is False
        and result.get("executed") is False
        and result.get("read_only") is True
        and result.get("cleanup_required") is False
        and "terminal_control" not in result
    ):
        raise ValueError("Invalid read_file control boundary")
    validate(request["arguments"])
