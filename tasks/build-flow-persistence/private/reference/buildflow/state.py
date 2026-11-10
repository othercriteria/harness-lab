import copy
import json
import os
import re
import tempfile
from pathlib import Path

from .spec import safe_path, valid_id


def validate_state(state):
    if (
        not isinstance(state, dict)
        or set(state) != {"version", "completed"}
        or type(state["version"]) is not int
        or state["version"] not in (1, 2)
        or not isinstance(state["completed"], dict)
    ):
        raise ValueError("invalid state")

    def valid_hash(value):
        return (
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
        )

    for name, receipt in state["completed"].items():
        if not valid_id(name):
            raise ValueError("invalid receipt id")
        if state["version"] == 1:
            if not valid_hash(receipt):
                raise ValueError("invalid legacy receipt")
        elif (
            not isinstance(receipt, dict)
            or set(receipt) != {"fingerprint", "outputs"}
            or not valid_hash(receipt["fingerprint"])
            or not isinstance(receipt["outputs"], dict)
            or any(
                not safe_path(p) or not valid_hash(h)
                for p, h in receipt["outputs"].items()
            )
        ):
            raise ValueError("invalid artifact receipt")
    return {
        "version": 2,
        "completed": copy.deepcopy(state["completed"]) if state["version"] == 2 else {},
    }


def load_state(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return validate_state(json.load(stream))
    except FileNotFoundError:
        return {"version": 2, "completed": {}}


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
