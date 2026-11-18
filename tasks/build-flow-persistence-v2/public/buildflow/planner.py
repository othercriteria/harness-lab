import hashlib
from pathlib import Path

from .spec import parse_spec


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan(spec, root, previous=None, targets=None):
    steps = parse_spec(spec)
    root = Path(root)
    return [
        {
            "id": name,
            "deps": step["deps"],
            "command": step["command"],
            "fingerprint": hashlib.sha256(name.encode()).hexdigest(),
            "cached": False,
        }
        for name, step in steps.items()
        if targets is None or name in targets
    ]
