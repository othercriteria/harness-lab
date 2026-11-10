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


def plan(spec, root, previous=None, targets=None):
    steps = parse_spec(spec)
    previous = validate_state(
        {"version": 1, "completed": {}} if previous is None else previous
    )
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("root must be a real directory")
    if targets is None:
        selected = set(steps)
    else:
        if not isinstance(targets, list) or any(
            not valid_id(x) or x not in steps for x in targets
        ):
            raise ValueError("invalid target")
        selected = set()

        def include(name):
            if name in selected:
                return
            selected.add(name)
            for dep in steps[name]["deps"]:
                include(dep)

        for name in targets:
            include(name)
    fingerprints, result = {}, []
    while selected:
        name = min(
            n for n in selected if all(d in fingerprints for d in steps[n]["deps"])
        )
        selected.remove(name)
        step = steps[name]
        inputs = []
        for relative in step["inputs"]:
            path = root
            for part in relative.split("/"):
                path = path / part
                if path.is_symlink():
                    raise ValueError("symlink input")
            if not path.is_file():
                raise ValueError("input must be a regular file")
            inputs.append([relative, digest_file(path)])
        payload = {
            "id": name,
            "command": step["command"],
            "inputs": inputs,
            "deps": [[d, fingerprints[d]] for d in step["deps"]],
        }
        digest = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        fingerprints[name] = digest
        result.append(
            {
                "id": name,
                "deps": list(step["deps"]),
                "command": list(step["command"]),
                "fingerprint": digest,
                "cached": previous["completed"].get(name) == digest,
            }
        )
    return result
