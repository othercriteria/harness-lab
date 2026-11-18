import hashlib
import json
from pathlib import Path

from .spec import parse_spec, valid_id
from .state import validate_state


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_path(root, relative, required=False):
    path = root
    parts = relative.split("/")
    for i, part in enumerate(parts):
        path = path / part
        if path.is_symlink():
            raise ValueError("symlink artifact or input")
        if path.exists():
            if i < len(parts) - 1 and not path.is_dir():
                raise ValueError("non-directory path component")
            if i == len(parts) - 1 and not path.is_file():
                raise ValueError("not a regular file")
    if required and not path.is_file():
        raise ValueError("missing regular file")
    return path


def prepare(spec, root, previous, targets):
    steps = parse_spec(spec)
    old = validate_state(
        {"version": 2, "completed": {}} if previous is None else previous
    )
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("root must be a real directory")
    if targets is None:
        selected = set(steps)
    else:
        if not isinstance(targets, list) or any(
            not valid_id(n) or n not in steps for n in targets
        ):
            raise ValueError("invalid targets")
        selected = set()

        def include(name):
            if name not in selected:
                selected.add(name)
                for dep in steps[name]["deps"]:
                    include(dep)

        for name in targets:
            include(name)
    order = []
    while selected:
        name = min(n for n in selected if all(d in order for d in steps[n]["deps"]))
        selected.remove(name)
        order.append(name)
    generated = {p for s in steps.values() for p in s["outputs"]}
    for name in order:
        step = steps[name]
        for path in step["outputs"]:
            checked_path(root, path)
        for path in step["inputs"]:
            resolved = checked_path(root, path, required=path not in generated)
            if path not in generated:
                digest_file(
                    resolved
                )  # All selected source I/O validated before callbacks.
    return steps, root, old, order


def fingerprint(step, root, fingerprints):
    payload = {
        "id": step["id"],
        "command": step["command"],
        "inputs": [
            [p, digest_file(checked_path(root, p, True))] for p in step["inputs"]
        ],
        "deps": [[d, fingerprints[d]] for d in step["deps"]],
        "outputs": list(step["outputs"]),
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def output_hashes(step, root):
    return {p: digest_file(checked_path(root, p, True)) for p in step["outputs"]}


def reusable(step, root, digest, old):
    receipt = old["completed"].get(step["id"])
    if (
        not receipt
        or receipt["fingerprint"] != digest
        or set(receipt["outputs"]) != set(step["outputs"])
    ):
        return False
    # Missing output is a cache miss, not a planning error. Unsafe existing paths
    # have already failed preflight; other I/O errors must propagate.
    if any(not checked_path(root, p).exists() for p in step["outputs"]):
        return False
    return output_hashes(step, root) == receipt["outputs"]


def plan(spec, root, previous=None, targets=None):
    steps, root, old, order = prepare(spec, root, previous, targets)
    rows, fingerprints, dispositions = [], {}, {}
    for name in order:
        step = steps[name]
        if any(dispositions[d] != "cached" for d in step["deps"]):
            digest, disposition = None, "deferred"
        else:
            digest = fingerprint(step, root, fingerprints)
            disposition = "cached" if reusable(step, root, digest, old) else "run"
        fingerprints[name], dispositions[name] = digest, disposition
        rows.append(
            {
                "id": name,
                "deps": list(step["deps"]),
                "command": list(step["command"]),
                "outputs": list(step["outputs"]),
                "fingerprint": digest,
                "disposition": disposition,
            }
        )
    return rows
