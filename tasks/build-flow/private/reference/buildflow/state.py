import copy
import json
import os
import re
import tempfile
from pathlib import Path

from .spec import valid_id


def validate_state(state):
    if (
        not isinstance(state, dict)
        or set(state) != {"version", "completed"}
        or type(state["version"]) is not int
        or state["version"] != 1
        or not isinstance(state["completed"], dict)
    ):
        raise ValueError("invalid state")
    for name, digest in state["completed"].items():
        if (
            not valid_id(name)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("invalid receipt")
    return copy.deepcopy(state)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return validate_state(json.load(stream))
    except FileNotFoundError:
        return {"version": 1, "completed": {}}


def replace_file(source, destination):
    os.replace(source, destination)


def save_state(path, state):
    state = validate_state(state)
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, sort_keys=True)
            stream.flush()
        replace_file(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
