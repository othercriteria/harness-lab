"""Bounded public snapshots and patch artifacts for trusted outer delegation.

No candidate imports, shell execution, Git metadata, or checkout writes occur here.
The outer caller chooses every input and writable path. Candidate exports are data;
successful export does not imply code correctness or permission to apply changes.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from bounded_diff import DiffView

MAX_FILES = 2048
MAX_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
FORBIDDEN_PARTS = {
    ".git",
    ".aws",
    ".ssh",
    ".codex",
    ".agents",
    ".venv",
    "__pycache__",
    "private",
    "reference",
    "evaluation",
    "results",
}


def relative_path(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(part in ("", ".", "..") for part in value.split("/"))
        or not re.fullmatch(r"[a-zA-Z0-9_./-]+", value)
        or any(
            part in FORBIDDEN_PARTS or part.startswith(".env")
            for part in value.split("/")
        )
    ):
        raise ValueError(f"Unapproved relative path: {value!r}")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_file(root, name, *, missing=False, limit=MAX_BYTES, with_mode=False):
    """Read a regular single-link file through no-follow directory descriptors."""
    relative_path(name)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = name.split("/")
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        file_fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        with os.fdopen(file_fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError(f"Not a regular single-link file: {name}")
            if before.st_size > limit:
                raise ValueError("File byte limit exceeded")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(data) > limit or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("File changed during bounded read")
            return (data, before.st_mode & 0o111) if with_mode else data
    except FileNotFoundError:
        if missing:
            return None
        raise
    finally:
        os.close(fd)


def selected_files(root, names, *, with_modes=False):
    if not isinstance(names, list) or not names or len(names) > MAX_FILES:
        raise ValueError("Expected a bounded nonempty explicit file list")
    for name in names:
        relative_path(name)
    if len(set(names)) != len(names):
        raise ValueError("Duplicate selected path")
    result, modes = {}, {}
    total = 0
    for name in sorted(names):
        data, mode = read_file(root, name, with_mode=True)
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError("Snapshot byte limit exceeded")
        result[name] = data
        modes[name] = mode
    return (result, modes) if with_modes else result


def validate_writable(names):
    if not isinstance(names, list) or not names or len(names) > MAX_FILES:
        raise ValueError("Expected a bounded nonempty allowed-write list")
    for name in names:
        relative_path(name)
        if name == "task.md":
            raise ValueError("task.md is reserved for the public job brief")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate allowed-write path")
    # A path may not be both a file and a parent directory.
    for name in names:
        if any(name.startswith(other + "/") for other in names):
            raise ValueError("Overlapping file and directory paths")


def create_snapshot(repo, names, writable, destination):
    """Outer-only preparation. Explicit selections; never recursively copy repo."""
    files, modes = selected_files(repo, names, with_modes=True)
    if "task.md" in files:
        raise ValueError("task.md is reserved for the public job brief")
    validate_writable(writable)
    base = {name: digest(data) for name, data in files.items()}
    for name in writable:
        if name not in base:
            if read_file(repo, name, missing=True) is not None:
                raise ValueError("Existing writable files must be included as inputs")
            base[name] = None
    # Reject a new file whose parent is an existing selected file.
    for name in base:
        if any(name.startswith(other + "/") for other in base):
            raise ValueError("Input/output file-directory collision")
    contract = {
        "version": 2,
        "inputs": {n: digest(b) for n, b in files.items()},
        "executable_bits": modes,
        "base": base,
        "allowed_write_paths": sorted(writable),
    }
    record = {"snapshot_id": digest(encoded(contract)), "contract": contract}
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    public = destination / "public"
    public.mkdir()
    for name, data in files.items():
        path = public / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o644 | modes[name])
    (destination / "snapshot.json").write_bytes(encoded(record) + b"\n")
    return record


def load_snapshot(snapshot):
    snapshot = Path(snapshot)
    record = json.loads(read_file(snapshot, "snapshot.json", limit=MAX_METADATA_BYTES))
    if set(record) != {"snapshot_id", "contract"}:
        raise ValueError("Invalid snapshot envelope")
    contract = record["contract"]
    if set(contract) != {
        "version",
        "inputs",
        "base",
        "allowed_write_paths",
        "executable_bits",
    }:
        raise ValueError("Invalid snapshot contract")
    if contract["version"] != 2 or digest(encoded(contract)) != record["snapshot_id"]:
        raise ValueError("Snapshot contract integrity mismatch")
    validate_writable(contract["allowed_write_paths"])
    files, modes = tree_files(snapshot / "public", with_modes=True)
    if {n: digest(b) for n, b in files.items()} != contract[
        "inputs"
    ] or modes != contract["executable_bits"]:
        raise ValueError("Snapshot input integrity mismatch")
    expected = contract["inputs"] | {
        n: None for n in contract["allowed_write_paths"] if n not in files
    }
    if contract["base"] != expected:
        raise ValueError("Snapshot base does not match input/write policy")
    return record, files


def tree_files(root, *, with_modes=False):
    """Enumerate a completed sandbox export; reject unexpected entries, not follow."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Invalid candidate root")
    names = []
    entries = 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            entries += 1
            if entries > MAX_FILES * 2:
                raise ValueError("Candidate entry limit exceeded")
            path = Path(parent) / name
            relative_path(path.relative_to(root).as_posix())
            if path.is_symlink():
                raise ValueError("Candidate symlink")
        for name in files:
            names.append((Path(parent) / name).relative_to(root).as_posix())
    return (
        selected_files(root, names, with_modes=with_modes)
        if names
        else (({}, {}) if with_modes else {})
    )


def export_candidate(snapshot, workspace, destination, *, brief=None):
    """Normalize permitted file edits; no code execution or acceptance decision."""
    record, before = load_snapshot(snapshot)
    after, modes = tree_files(workspace, with_modes=True)
    if brief is not None:
        if after.pop("task.md", None) != brief or modes.pop("task.md", None) != 0:
            raise ValueError("Public job brief changed or disappeared")
    for name, mode in modes.items():
        if mode != record["contract"]["executable_bits"].get(name, 0):
            raise ValueError(f"Executable-mode changes are not allowed: {name}")
    allowed = set(record["contract"]["allowed_write_paths"])
    changed = sorted(
        n for n in before.keys() | after.keys() if before.get(n) != after.get(n)
    )
    forbidden = set(changed) - allowed
    if forbidden:
        raise ValueError(f"Candidate changed unapproved paths: {sorted(forbidden)}")
    rows = []
    diff = DiffView()
    for name in changed:
        left, right = before.get(name), after.get(name)
        # First MVP supports text patches; binary work needs explicit later policy.
        for data in (left, right):
            if data is not None:
                data.decode("utf-8")
                if b"\0" in data:
                    raise ValueError("Binary patch unsupported")
        rows.append(
            {
                "path": name,
                "before_sha256": digest(left) if left is not None else None,
                "after_sha256": digest(right) if right is not None else None,
                "executable_bits": modes.get(name),
                "operation": "delete"
                if right is None
                else "add"
                if left is None
                else "modify",
            }
        )
        diff.add(name, left, right)
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    (destination / "files").mkdir()
    for row in rows:
        if row["after_sha256"] is not None:
            path = destination / "files" / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(after[row["path"]])
            path.chmod(0o644 | row["executable_bits"])
    diff_bytes = diff.render().encode()
    (destination / "changes.diff").write_bytes(diff_bytes)
    artifact = {
        "version": 1,
        "snapshot_id": record["snapshot_id"],
        "changes": rows,
        "diff_sha256": digest(diff_bytes),
        "diff_display": {
            "omitted_files": diff.omitted_files,
            "fallback_files": diff.fallback_files,
            "algorithm": "bounded linear changed-span hunks",
        },
        "acceptance": "pending_outer_review",
        "applied": False,
    }
    (destination / "artifact.json").write_bytes(encoded(artifact) + b"\n")
    return artifact


def check_application_base(snapshot, repo):
    """Check every supplied dependency and output path, not only edited files."""
    record, _ = load_snapshot(snapshot)
    stale = []
    for name, expected in record["contract"]["base"].items():
        value = read_file(repo, name, missing=True, with_mode=True)
        actual = digest(value[0]) if value is not None else None
        mode = value[1] if value is not None else None
        if actual != expected or mode != record["contract"]["executable_bits"].get(
            name
        ):
            stale.append(name)
    if stale:
        raise ValueError(f"Stale snapshot base: {stale}")
    return {
        "snapshot_id": record["snapshot_id"],
        "base_matches": True,
        "note": "Preflight only; not an atomic checkout update or permission to apply.",
    }
