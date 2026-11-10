"""Optional immutable Python test libraries for model tool sandboxes only."""

import hashlib
import json
import re
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "configs/python-test-libraries.json"
NAMES = ("hypothesis",)
INSTRUCTION = (
    "\n\nHypothesis is optional, available through bash when a useful property adds"
    " coverage beyond a few explicit examples."
    " Choose input strategies and properties from the public contract; generated"
    " inputs may be outside its domain and your assertions may be wrong."
    " Bound runs with @settings(max_examples=40, derandomize=True, database=None,"
    " deadline=None), and call decorated functions directly or use unittest methods."
    " The tool timeout still applies. This is a test-only library; obey the task's"
    " implementation dependency restrictions. It is not available to the evaluator."
)


def validate(name):
    if not isinstance(name, str) or name not in NAMES:
        raise ValueError("Unknown python_test_library")


def load(name, catalog=CATALOG):
    validate(name)
    raw = Path(catalog).read_bytes()
    data = json.loads(raw)[name]
    minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if data["python_version"] != minor:
        raise ValueError("Test library Python version differs from runtime")
    roots, paths = [], []
    for package in data["packages"]:
        root = Path(package["store_path"])
        if (
            root.parent != Path("/nix/store")
            or not re.fullmatch(r"[a-z0-9]{32}-[A-Za-z0-9+._-]+", root.name)
            or not root.is_dir()
            or root.resolve() != root
        ):
            raise ValueError("Test libraries require immutable Nix store roots")
        path = root / "lib" / ("python" + minor) / "site-packages"
        if not path.is_dir() or path.resolve() != path:
            raise ValueError("Test library import path is missing or redirected")
        roots.append(str(root))
        paths.append(str(path))
    if not roots or len(roots) != len(set(roots)):
        raise ValueError("Test libraries require distinct package roots")
    return {
        "name": name,
        "catalog_sha256": hashlib.sha256(raw).hexdigest(),
        "python_version": minor,
        "packages": data["packages"],
        "roots": roots,
        "python_paths": paths,
    }
