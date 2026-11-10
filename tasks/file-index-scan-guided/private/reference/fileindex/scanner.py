import hashlib
import os
import stat
from pathlib import Path

from .catalog import validate


def scan_tree(root, previous=None):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("root must be a real directory")
    old = validate(previous)["files"] if previous is not None else {}
    found = {}

    def onerror(error):
        raise error

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            path = Path(directory) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            key = path.relative_to(root).as_posix()
            prior = old.get(key)
            if (
                prior is not None
                and prior["size"] == info.st_size
                and prior["mtime_ns"] == info.st_mtime_ns
            ):
                digest = prior["sha256"]
            else:
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(65536):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
            found[key] = {
                "size": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "sha256": digest,
            }
    return validate({"version": 1, "files": dict(sorted(found.items()))})
