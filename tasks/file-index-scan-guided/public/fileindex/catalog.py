import json
import os
import re
import tempfile
from pathlib import Path


def validate(catalog):
    if (
        not isinstance(catalog, dict)
        or set(catalog) != {"version", "files"}
        or type(catalog["version"]) is not int
        or catalog["version"] != 1
        or not isinstance(catalog["files"], dict)
    ):
        raise ValueError("invalid catalog header")
    for name, entry in catalog["files"].items():
        if (
            not isinstance(name, str)
            or "\\" in name
            or any(p in ("", ".", "..") for p in name.split("/"))
        ):
            raise ValueError("unsafe catalog path")
        if not isinstance(entry, dict) or set(entry) != {"size", "mtime_ns", "sha256"}:
            raise ValueError("invalid file entry")
        if any(type(entry[k]) is not int or entry[k] < 0 for k in ("size", "mtime_ns")):
            raise ValueError("invalid stat metadata")
        if (
            not isinstance(entry["sha256"], str)
            or re.fullmatch("[0-9a-f]{64}", entry["sha256"]) is None
        ):
            raise ValueError("invalid digest")
    return catalog


def load_catalog(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return validate(json.load(stream))
    except FileNotFoundError:
        return {"version": 1, "files": {}}


def save_catalog(path, catalog):
    validate(catalog)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(catalog, stream)
            stream.flush()
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def diff_catalogs(old, new):
    validate(old)
    validate(new)
    left, right = old["files"], new["files"]
    return {
        "added": sorted(right.keys() - left.keys()),
        "removed": sorted(left.keys() - right.keys()),
        "changed": sorted(
            k
            for k in left.keys() & right.keys()
            if left[k]["sha256"] != right[k]["sha256"]
        ),
    }
