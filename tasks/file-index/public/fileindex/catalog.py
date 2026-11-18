import json
from pathlib import Path


def load_catalog(path):
    path = Path(path)
    if not path.exists():
        return {"version": 1, "files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_catalog(path, catalog):
    Path(path).write_text(json.dumps(catalog), encoding="utf-8")


def diff_catalogs(old, new):
    return {
        "added": sorted(set(new["files"]) - set(old["files"])),
        "removed": [],
        "changed": [],
    }
